import asyncio
import hashlib
import json
import logging
import re
import secrets
import smtplib
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from .config import settings
from . import notifier
from .mercator import MercatorClient, MercatorError
from .report import SCOPE_LABEL, build_pdf

log = logging.getLogger("certs")
STATIC = Path(__file__).parent / "static"
STATUS_LABELS = {0: "Good", 1: "Revoked", 2: "Unknown"}  # RFC 6960, cf. docs Mercator

client = MercatorClient(
    settings.mercator_url, settings.mercator_login, settings.mercator_password,
    verify=settings.mercator_verify_tls, timeout=settings.mercator_timeout,
)

# ---------------------------------------------------------------- sécurité
_basic = HTTPBasic(auto_error=False)


def require_auth(creds: HTTPBasicCredentials | None = Depends(_basic)):
    """HTTP Basic optionnel : actif seulement si APP_BASIC_USER est défini."""
    if not settings.basic_user:
        return ""
    ok = creds is not None \
        and secrets.compare_digest(creds.username.encode(), settings.basic_user.encode()) \
        and secrets.compare_digest(creds.password.encode(), settings.basic_password.encode())
    if not ok:
        raise HTTPException(401, "Authentification requise",
                            headers={"WWW-Authenticate": 'Basic realm="certs"'})
    return creds.username


async def _notify_loop():
    """Contrôle périodique des seuils d'expiration et envoi des mails."""
    while True:
        try:
            await cache.get()
            if cache.items:
                await notifier.check_and_notify(
                    cache.items, datetime.now(timezone.utc).isoformat())
        except (MercatorError, OSError, smtplib.SMTPException) as e:
            log.warning("Contrôle des notifications en échec : %s", e)
        await asyncio.sleep(max(60, settings.notify_interval))


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(_notify_loop()) if notifier.enabled() else None
    yield
    if task:
        task.cancel()


app = FastAPI(title=settings.app_title, dependencies=[Depends(require_auth)], lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def no_cache_ui(request: Request, call_next):
    """L'interface (HTML/JS/CSS) est revalidée à chaque chargement : après une mise à jour de
    l'app, les navigateurs ne gardent pas l'ancienne version en cache."""
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


# ------------------------------------------------------------ normalisation
def _date(v) -> date | None:
    """Mercator renvoie 'YYYY-MM-DD' ou un ISO complet : on garde les 10 premiers caractères."""
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _links(raw: dict, *keys: str) -> list[dict]:
    for k in keys:
        items = raw.get(k)
        if isinstance(items, list):
            return [{"id": i.get("id"), "name": i.get("name") or f"#{i.get('id')}"}
                    for i in items if isinstance(i, dict)]
    return []


def category_of(type_: str) -> str:
    """certificate (défaut) | license | domain, d'après des mots-clés dans la colonne « type »."""
    t = (type_ or "").lower()
    if any(k in t for k in settings.domain_keywords):
        return "domain"
    if any(k in t for k in settings.license_keywords):
        return "license"
    return "certificate"


def expiry_state(days_left: int | None, status: int | None) -> str:
    if status == 1:
        return "revoked"
    if days_left is None:
        return "nodate"
    if days_left < 0:
        return "expired"
    if days_left <= settings.critical_days:
        return "critical"
    if days_left <= settings.warning_days:
        return "warning"
    return "valid"


def normalize(raw: dict, today: date) -> dict:
    start, end = _date(raw.get("start_validity")), _date(raw.get("end_validity"))
    days_left = (end - today).days if end else None
    try:
        status = int(raw["status"]) if raw.get("status") is not None else None
    except (TypeError, ValueError):
        status = None
    return {
        "id": raw.get("id"),
        "uid": raw.get("uuid") or raw.get("uid"),
        "name": raw.get("name") or "",
        "description": raw.get("description") or "",
        "type": raw.get("type") or "",
        "category": category_of(raw.get("type")),
        "ext_refs": raw.get("ext_refs") or "",
        "start_validity": start.isoformat() if start else None,
        "end_validity": end.isoformat() if end else None,
        "days_left": days_left,
        "status": status,
        "status_label": STATUS_LABELS.get(status, ""),
        "state": expiry_state(days_left, status),
        "logical_servers": _links(raw, "logical_servers", "logicalServers"),
        "applications": _links(raw, "applications"),
        "updated_at": raw.get("updated_at"),
    }


# ------------------------------------------------------------------- cache
class Cache:
    def __init__(self):
        self.items: list[dict] = []
        self.fetched_at: float = 0.0
        self.error: str | None = None
        self._lock = asyncio.Lock()

    async def get(self, force: bool = False) -> None:
        fresh = self.fetched_at and (time.time() - self.fetched_at) < settings.cache_ttl
        if fresh and not force:
            return
        async with self._lock:
            # un autre appel concurrent a peut-être déjà rafraîchi
            if not force and self.fetched_at and (time.time() - self.fetched_at) < settings.cache_ttl:
                return
            try:
                raw = await client.certificates()
                today = date.today()
                self.items = [normalize(r, today) for r in raw]
                self.fetched_at = time.time()
                self.error = None
            except MercatorError as e:
                self.error = str(e)
                if not self.items:      # rien à servir : on remonte l'erreur
                    raise


cache = Cache()


def _summary(items: list[dict]) -> dict:
    counts = {k: 0 for k in ("valid", "warning", "critical", "expired", "revoked", "nodate")}
    for c in items:
        counts[c["state"]] += 1
    return {"total": len(items), **counts,
            "certificates": sum(c["category"] == "certificate" for c in items),
            "licenses": sum(c["category"] == "license" for c in items),
            "domains": sum(c["category"] == "domain" for c in items)}


# --------------------------------------------------------------------- API
@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/certificates")
async def list_certificates(refresh: bool = False):
    try:
        await cache.get(force=refresh)
    except MercatorError as e:
        return JSONResponse({"detail": str(e)}, status_code=e.status)
    return {
        "items": cache.items,
        "summary": _summary(cache.items),
        "fetched_at": datetime.fromtimestamp(cache.fetched_at, timezone.utc).isoformat(),
        "stale_error": cache.error,   # non nul = données en cache car Mercator a échoué
        "thresholds": {"critical": settings.critical_days, "warning": settings.warning_days},
        "mercator_public_url": settings.mercator_public_url,
        "title": settings.app_title,
    }


# ------------------------------------------------------- notifications mail
@app.get("/api/notifications")
async def notifications_status():
    return {"enabled": notifier.enabled(), "thresholds": settings.notify_thresholds,
            "recipients": settings.mail_to, "categories": settings.notify_categories,
            "interval": settings.notify_interval, "last_run": notifier.last_run}


@app.post("/api/notifications/test")
async def notifications_test():
    """Envoie un mail de test pour valider la configuration SMTP."""
    if not notifier.enabled():
        return JSONResponse({"detail": "Notifications non configurées (SMTP_HOST, MAIL_TO)."}, status_code=400)
    try:
        await notifier.send_test()
    except (OSError, smtplib.SMTPException) as e:
        return JSONResponse({"detail": f"Envoi impossible : {e.__class__.__name__}: {e}"}, status_code=502)
    return {"ok": True}


# ----------------------------------------------------- rapports de contrôle
REPORTS = Path(settings.reports_dir)
INDEX = REPORTS / "index.jsonl"
ID_RE = re.compile(r"^CTRL-\d{8}-\d{6}-[0-9a-f]{4}$")


class ReportRequest(BaseModel):
    controller: str = Field(min_length=2, max_length=100)
    comment: str = Field("", max_length=1000)
    category: Literal["", "certificate", "license", "domain"] = ""


@app.post("/api/reports")
async def create_report(req: ReportRequest, user: str = Depends(require_auth)):
    """Relit Mercator EN DIRECT (cache ignoré), génère le PDF d'attestation et l'archive.
    Refus si Mercator est injoignable : un rapport de contrôle ne doit jamais reposer sur des données périmées."""
    try:
        await cache.get(force=True)
    except MercatorError as e:
        return JSONResponse({"detail": f"Contrôle impossible : {e}"}, status_code=e.status)
    if cache.error:
        return JSONResponse({"detail": "Contrôle impossible : Mercator injoignable, "
                                       "les données en cache ne sont pas assez récentes pour attester d'un contrôle."},
                            status_code=502)

    tz = ZoneInfo(settings.report_tz)
    now = datetime.now(tz)
    fetched = datetime.fromtimestamp(cache.fetched_at, tz)
    items = [c for c in cache.items if not req.category or c["category"] == req.category]
    rid = f"CTRL-{now:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    source = f"{settings.mercator_url}/api/certificates"

    snapshot = {"report_id": rid, "generated_at": now.isoformat(), "fetched_at": fetched.isoformat(),
                "source": source, "scope": req.category or "all",
                "thresholds": {"critical": settings.critical_days, "warning": settings.warning_days},
                "items": items}
    snap_bytes = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, indent=1).encode("utf-8")
    digest = hashlib.sha256(snap_bytes).hexdigest()

    pdf = build_pdf({
        "report_id": rid, "generated_at": now, "fetched_at": fetched, "controller": req.controller.strip(),
        "user": user, "comment": req.comment, "category": req.category, "tz_name": settings.report_tz,
        "source": source, "service_account": settings.mercator_login,
        "thresholds": snapshot["thresholds"], "sha256": digest}, items)

    summary = _summary(items)
    entry = {"id": rid, "generated_at": now.isoformat(), "controller": req.controller.strip(), "user": user,
             "scope": req.category, "sha256": digest, "total": summary["total"], "expired": summary["expired"],
             "critical": summary["critical"], "warning": summary["warning"], "revoked": summary["revoked"]}
    try:
        REPORTS.mkdir(parents=True, exist_ok=True)
        (REPORTS / f"{rid}.pdf").write_bytes(pdf)
        (REPORTS / f"{rid}.json").write_bytes(snap_bytes)
        with INDEX.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        return JSONResponse({"detail": f"Archivage impossible : le dossier {settings.reports_dir} n'est pas "
                                       "inscriptible (volume Docker manquant ?). Rapport non généré."},
                            status_code=500)
    return entry


@app.get("/api/reports")
async def list_reports(limit: int = 50):
    if not INDEX.exists():
        return []
    lines = INDEX.read_text(encoding="utf-8").splitlines()
    out = []
    for ln in reversed(lines[-max(1, min(limit, 500)):]):
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def _report_file(rid: str, ext: str) -> Path:
    if not ID_RE.match(rid):          # empêche toute traversée de chemin
        raise HTTPException(404)
    p = REPORTS / f"{rid}.{ext}"
    if not p.is_file():
        raise HTTPException(404)
    return p


@app.get("/api/reports/{rid}/pdf")
async def report_pdf(rid: str):
    return FileResponse(_report_file(rid, "pdf"), media_type="application/pdf", filename=f"{rid}.pdf")


@app.get("/api/reports/{rid}/json")
async def report_json(rid: str):
    return FileResponse(_report_file(rid, "json"), media_type="application/json", filename=f"{rid}.json")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
