"""Notifications e-mail d'expiration selon des seuils (en jours).

Principe : pour chaque élément on calcule son « palier » = le plus petit seuil S tel que
jours_restants <= S (ou -1 si déjà expiré). Un mail n'est envoyé que lorsque le palier
DESCEND par rapport au dernier palier notifié pour cette même date d'échéance (donc une
seule alerte par seuil franchi). Si la date d'échéance change (renouvellement), le suivi
repart de zéro. Les éléments révoqués ou sans date sont ignorés.
Un seul mail récapitulatif est envoyé par contrôle ; l'état n'est enregistré qu'après envoi réussi.
"""
import asyncio
import json
import logging
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from .config import settings

log = logging.getLogger("notifier")
EXPIRED = -1
CATEGORY_LABEL = {"certificate": "Certificat", "license": "Licence", "domain": "Domaine"}


def enabled() -> bool:
    return bool(settings.smtp_host and settings.mail_to and settings.notify_thresholds)


def level_of(days_left: int, thresholds: list[int]) -> int | None:
    """Palier atteint : EXPIRED si échu, sinon le plus petit seuil >= jours restants, None si au-dessus de tous."""
    if days_left < 0:
        return EXPIRED
    reached = [t for t in thresholds if days_left <= t]
    return min(reached) if reached else None


def due_items(items: list[dict], state: dict, thresholds: list[int],
              categories: list[str] | None = None) -> tuple[list[dict], dict]:
    """Retourne (éléments à notifier, nouvel état). Pure : sans effet de bord."""
    new_state: dict[str, dict] = {}
    due: list[dict] = []
    for c in items:
        if c.get("state") in ("revoked", "nodate") or c.get("days_left") is None:
            continue
        if categories and c["category"] not in categories:
            continue
        key = str(c["id"])
        lvl = level_of(c["days_left"], thresholds)
        prev = state.get(key)
        same_end = prev is not None and prev.get("end") == c["end_validity"]
        prev_lvl = prev.get("level") if same_end else None
        if lvl is None:
            # au-dessus de tous les seuils (ex. renouvelé) : on oublie, rien à notifier
            continue
        if prev_lvl is None or lvl < prev_lvl:
            due.append({**c, "level": lvl})
            new_state[key] = {"end": c["end_validity"], "level": lvl}
        else:
            new_state[key] = prev
    return due, new_state


def _level_text(lvl: int) -> str:
    return "EXPIRÉ" if lvl == EXPIRED else ("expire aujourd'hui" if lvl == 0 else f"seuil {lvl} j franchi")


def build_message(due: list[dict]) -> EmailMessage:
    due = sorted(due, key=lambda c: (c["days_left"], c["name"].lower()))
    n_exp = sum(c["level"] == EXPIRED for c in due)
    subject = f"[{settings.app_title}] {len(due)} échéance(s) à traiter" + (f" dont {n_exp} expirée(s)" if n_exp else "")
    lines = [f"{len(due)} élément(s) ont franchi un seuil d'alerte ({', '.join(str(t) for t in settings.notify_thresholds)} jours) :", ""]
    for c in due:
        d = c["days_left"]
        when = f"expiré depuis {-d} j" if d < 0 else ("expire aujourd'hui" if d == 0 else f"expire dans {d} j")
        link = (f"  {settings.mercator_public_url}/admin/certificates/{c['id']}/edit"
                if settings.mercator_public_url else "")
        lines.append(f"- [{CATEGORY_LABEL.get(c['category'], c['category'])}] {c['name']} — {c['end_validity']} ({when}; {_level_text(c['level'])})")
        if link:
            lines.append(link)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.mail_from or settings.smtp_user or "mercator-certs@localhost"
    msg["To"] = ", ".join(settings.mail_to)
    msg.set_content("\n".join(lines))
    return msg


def _send(msg: EmailMessage) -> None:
    ctx = ssl.create_default_context()
    if settings.smtp_security == "ssl":
        smtp = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30, context=ctx)
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
    with smtp:
        if settings.smtp_security == "starttls":
            smtp.starttls(context=ctx)
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


def _load_state() -> dict:
    try:
        return json.loads(Path(settings.notify_state_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    p = Path(settings.notify_state_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


_lock = asyncio.Lock()
last_run: dict = {"at": None, "sent": 0, "error": None}


async def check_and_notify(items: list[dict], now_iso: str) -> int:
    """Envoie le mail récapitulatif des éléments nouvellement au-delà d'un seuil. Retourne le nombre notifié."""
    async with _lock:
        due, new_state = due_items(items, _load_state(), settings.notify_thresholds,
                                   settings.notify_categories)
        try:
            if due:
                await asyncio.to_thread(_send, build_message(due))
            _save_state(new_state)
            last_run.update(at=now_iso, sent=len(due), error=None)
            if due:
                log.info("Notification envoyée pour %d élément(s)", len(due))
            return len(due)
        except (OSError, smtplib.SMTPException) as e:
            last_run.update(at=now_iso, sent=0, error=f"{e.__class__.__name__}: {e}")
            log.error("Envoi de la notification impossible : %s", e)
            raise


async def send_test() -> None:
    msg = EmailMessage()
    msg["Subject"] = f"[{settings.app_title}] Test de notification"
    msg["From"] = settings.mail_from or settings.smtp_user or "mercator-certs@localhost"
    msg["To"] = ", ".join(settings.mail_to)
    msg.set_content("La configuration SMTP fonctionne.\nSeuils : "
                    + ", ".join(str(t) for t in settings.notify_thresholds) + " jours.")
    await asyncio.to_thread(_send, msg)
