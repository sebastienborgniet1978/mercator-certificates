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

    app_title: str = os.getenv("APP_TITLE", "Certificats – Mercator")


settings = Settings()
