import hashlib
import json
import os
import subprocess
import tempfile
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
FAKE = "http://127.0.0.1:9101"


@pytest.fixture(scope="module")
def fake():
    p = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "fake_mercator:app", "--port", "9101", "--log-level", "warning"],
        cwd=ROOT / "tests")
    for _ in range(50):
        try:
            httpx.get(FAKE + "/__calls"); break
        except httpx.HTTPError:
            time.sleep(0.1)
    yield
    p.terminate()


@pytest.fixture(scope="module")
def api(fake):
    REPORTS = tempfile.mkdtemp()
    os.environ.update(REPORTS_DIR=REPORTS, MERCATOR_URL=FAKE, MERCATOR_LOGIN="svc", MERCATOR_PASSWORD="pw", CACHE_TTL="300")
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


def by_name(items):
    return {c["name"]: c for c in items}


def test_list_and_states(api):
    r = api.get("/api/certificates")
    assert r.status_code == 200
    body = r.json()
    c = by_name(body["items"])
    assert c["wildcard.bpp.local"]["state"] == "warning" and c["wildcard.bpp.local"]["days_left"] == 65
    assert c["mail.example.com"]["state"] == "expired"           # date ISO complète parsée
    assert c["vpn.example.com"]["state"] == "critical"
    assert c["old-revoked"]["state"] == "revoked"                # révoqué prime sur la date
    assert c["no-date"]["state"] == "nodate" and c["no-date"]["days_left"] is None
    assert c["ok-long"]["state"] == "valid"
    assert body["summary"] == {"total": 10, "valid": 2, "warning": 2, "critical": 2,
                               "expired": 2, "revoked": 1, "nodate": 1,
                               "certificates": 6, "licenses": 2, "domains": 2}


def test_relations_both_key_styles(api):
    c = by_name(api.get("/api/certificates").json()["items"])
    assert c["wildcard.bpp.local"]["logical_servers"] == [{"id": 7, "name": "SRV-WEB01"}]
    assert c["ok-long"]["logical_servers"][0]["name"] == "SRV-CAMEL"   # clé camelCase
    assert c["no-date"]["type"] == ""


def test_cache_and_refresh(api):
    api.get("/api/certificates")
    before = httpx.get(FAKE + "/__calls").json()["certs"]
    api.get("/api/certificates"); api.get("/api/certificates")
    assert httpx.get(FAKE + "/__calls").json()["certs"] == before     # servi depuis le cache
    api.get("/api/certificates?refresh=true")
    assert httpx.get(FAKE + "/__calls").json()["certs"] == before + 1


def test_token_reuse_and_relogin_on_401(api):
    logins = httpx.get(FAKE + "/__calls").json()["login"]
    api.get("/api/certificates?refresh=true")
    assert httpx.get(FAKE + "/__calls").json()["login"] == logins     # token réutilisé
    httpx.post(FAKE + "/__expire")
    r = api.get("/api/certificates?refresh=true")
    assert r.status_code == 200 and r.json()["stale_error"] is None
    assert httpx.get(FAKE + "/__calls").json()["login"] == logins + 1  # re-login automatique


def test_stale_cache_when_mercator_down(api, fake):
    from app.main import client, cache
    old = client.base
    client.base = "http://127.0.0.1:9"          # injoignable
    try:
        r = api.get("/api/certificates?refresh=true")
        assert r.status_code == 200
        assert r.json()["stale_error"] and len(r.json()["items"]) == 10
    finally:
        client.base = old
        cache.error = None


def test_static_and_health(api):
    assert api.get("/api/health").json() == {"ok": True}
    assert "Certificats" in api.get("/").text
    assert api.get("/static/app.js").status_code == 200


def test_category_split_on_type(api):
    c = by_name(api.get("/api/certificates").json()["items"])
    assert c["Veeam socket"]["category"] == "license"
    assert c["Office E5"]["category"] == "license"          # "Licence Microsoft"
    assert c["wildcard.bpp.local"]["category"] == "certificate"
    assert c["no-date"]["category"] == "certificate"        # type vide


def test_report_generation_and_archive(api):
    r = api.post("/api/reports", json={"controller": "Sébastien Borgniet", "comment": "RAS é<b>x</b>", "category": ""})
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["id"].startswith("CTRL-") and e["total"] == 10 and e["expired"] == 2
    pdf = api.get(f"/api/reports/{e['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    snap = api.get(f"/api/reports/{e['id']}/json")
    assert hashlib.sha256(snap.content).hexdigest() == e["sha256"]      # empreinte vérifiable
    assert len(json.loads(snap.content)["items"]) == 10
    assert api.get("/api/reports").json()[0]["id"] == e["id"]
    # périmètre
    r2 = api.post("/api/reports", json={"controller": "AB", "category": "license"}).json()
    assert r2["total"] == 2


def test_report_refused_on_stale_data_and_bad_input(api, fake):
    from app.main import client, cache
    n = len(api.get("/api/reports").json())
    old = client.base
    client.base = "http://127.0.0.1:9"
    try:
        r = api.post("/api/reports", json={"controller": "Sébastien"})
        assert r.status_code == 502 and "Contrôle impossible" in r.json()["detail"]
    finally:
        client.base = old; cache.error = None
    assert len(api.get("/api/reports").json()) == n                     # aucun rapport créé
    assert api.post("/api/reports", json={"controller": "x"}).status_code == 422
    assert api.get("/api/reports/..%2F..%2Fetc%2Fpasswd/pdf").status_code == 404
    assert api.get("/api/reports/CTRL-20200101-000000-abcd/pdf").status_code == 404


def test_domain_category_and_scope(api):
    c = by_name(api.get("/api/certificates").json()["items"])
    assert c["example.com"]["category"] == "domain"
    assert c["example.lu"]["category"] == "domain"           # "Nom de domaine"
    assert c["Veeam socket"]["category"] == "license"        # inchangé
    r = api.post("/api/reports", json={"controller": "AB", "category": "domain"}).json()
    assert r["total"] == 2 and r["scope"] == "domain"


def test_ui_not_cached_and_has_domain_tab(api):
    r = api.get("/static/app.js")
    assert r.headers["cache-control"] == "no-cache"
    assert '["domain", "Domaines"]' in r.text
    assert api.get("/").headers["cache-control"] == "no-cache"
