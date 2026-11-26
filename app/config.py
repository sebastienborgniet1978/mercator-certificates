import os


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    # Mercator (couche REST Laravel/Passport)
    mercator_url: str = os.getenv("MERCATOR_URL", "http://mercator:8080").rstrip("/")
    mercator_login: str = os.getenv("MERCATOR_LOGIN", "")
    mercator_password: str = os.getenv("MERCATOR_PASSWORD", "")
    mercator_verify_tls: bool = _bool("MERCATOR_VERIFY_TLS", True)
    mercator_timeout: float = float(os.getenv("MERCATOR_TIMEOUT", "30"))
    # URL publique de Mercator, pour les liens "ouvrir dans Mercator" (optionnel)
    mercator_public_url: str = os.getenv("MERCATOR_PUBLIC_URL", "").rstrip("/")

    # Cache mémoire (secondes) : évite de solliciter Mercator à chaque affichage
    cache_ttl: int = int(os.getenv("CACHE_TTL", "300"))

    # Seuils d'alerte d'expiration (jours)
    critical_days: int = int(os.getenv("CRITICAL_DAYS", "30"))
    warning_days: int = int(os.getenv("WARNING_DAYS", "90"))

    # Protection optionnelle par HTTP Basic (à défaut : à protéger via le reverse proxy)
    basic_user: str = os.getenv("APP_BASIC_USER", "")
    basic_password: str = os.getenv("APP_BASIC_PASSWORD", "")

    # Idem pour les NOMS DE DOMAINE (« Domain », « Nom de domaine », « DNS »…)
    domain_keywords: list[str] = [k.strip().lower() for k in
                                  os.getenv("DOMAIN_TYPE_KEYWORDS", "domain,dns").split(",") if k.strip()]

    # Un « type » contenant l'un de ces mots-clés (insensible à la casse) = licence ;
    # tout le reste = certificat. « licen » couvre license / licence / licences.
    license_keywords: list[str] = [k.strip().lower() for k in
                                   os.getenv("LICENSE_TYPE_KEYWORDS", "licen").split(",") if k.strip()]

    # Archivage des rapports de contrôle (PDF + données sources + journal) : monter un volume ici
    reports_dir: str = os.getenv("REPORTS_DIR", "/data/reports")
    report_tz: str = os.getenv("REPORT_TZ", "Europe/Luxembourg")

    # Notifications e-mail d'expiration (actives si SMTP_HOST et MAIL_TO sont renseignés)
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_security: str = os.getenv("SMTP_SECURITY", "starttls").strip().lower()  # starttls | ssl | none
    mail_from: str = os.getenv("MAIL_FROM", "")
    mail_to: list[str] = [a.strip() for a in os.getenv("MAIL_TO", "").split(",") if a.strip()]
    # Seuils (jours avant échéance) : un mail est envoyé quand un élément franchit un seuil.
    notify_thresholds: list[int] = sorted(
        {int(x) for x in os.getenv("NOTIFY_THRESHOLDS", "60,30,15,7,0").split(",") if x.strip().lstrip("-").isdigit()},
        reverse=True)
    # Catégories surveillées (certificate, license, domain) ; vide = toutes
    notify_categories: list[str] = [c.strip().lower() for c in
                                    os.getenv("NOTIFY_CATEGORIES", "").split(",") if c.strip()]
    notify_interval: int = int(os.getenv("NOTIFY_CHECK_INTERVAL", "3600"))  # secondes entre deux contrôles
    notify_state_file: str = os.getenv("NOTIFY_STATE_FILE", "/data/notifications.json")

    app_title: str = os.getenv("APP_TITLE", "Certificats – Mercator")


settings = Settings()
