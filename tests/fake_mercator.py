"""Faux Mercator pour les tests : reproduit /api/login et /api/certificates
tels qu'implémentés dans le code source de Mercator (tableau JSON brut, include=...)."""
from datetime import date, timedelta

from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI()
TOKEN = "tok-123"
calls = {"login": 0, "certs": 0}


def d(n):
    return (date.today() + timedelta(days=n)).isoformat()


CERTS = [
    {"id": 1, "name": "wildcard.bpp.local", "type": "SSL", "description": "Wildcard interne",
     "start_validity": d(-300), "end_validity": d(65), "status": 0, "ext_refs": "{AD}42",
     "logical_servers": [{"id": 7, "name": "SRV-WEB01"}], "applications": [{"id": 3, "name": "Intranet"}],
     "updated_at": "2026-11-01T10:00:00.000000Z"},
    {"id": 2, "name": "mail.example.com", "type": "HTTPS", "description": "<script>alert(1)</script>",
     "start_validity": d(-400) + "T00:00:00.000000Z", "end_validity": d(-5) + "T00:00:00.000000Z",
     "status": 0, "logical_servers": [], "applications": []},
    {"id": 3, "name": "vpn.example.com", "type": "SSL", "start_validity": d(-10), "end_validity": d(12),
     "status": 0, "logical_servers": [{"id": 8, "name": "SRV-VPN"}], "applications": []},
    {"id": 4, "name": "old-revoked", "type": "SSL", "end_validity": d(200), "status": 1},
    {"id": 5, "name": "no-date", "type": None, "end_validity": None, "status": 2},
    {"id": 7, "name": "Veeam socket", "type": "License", "end_validity": d(40), "status": 0},
    {"id": 8, "name": "Office E5", "type": "Licence Microsoft", "end_validity": d(-1), "status": 0},
    {"id": 9, "name": "example.com", "type": "Domain", "end_validity": d(25), "status": 0},
    {"id": 10, "name": "example.lu", "type": "Nom de domaine", "end_validity": d(300), "status": 0},
    {"id": 6, "name": "ok-long", "type": "HTTPS", "end_validity": d(700), "status": 0,
     "logicalServers": [{"id": 9, "name": "SRV-CAMEL"}]},
]


@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    calls["login"] += 1
    if body.get("login") != "svc" or body.get("password") != "pw":
        raise HTTPException(400, "This user does not exist, check your details")
    return {"user": {"id": 1}, "access_token": TOKEN}


@app.get("/api/certificates")
async def certs(authorization: str | None = Header(None), include: str | None = None):
    calls["certs"] += 1
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "Unauthenticated")
    return CERTS


@app.get("/__calls")
async def get_calls():
    return calls


@app.post("/__expire")
async def expire():
    global TOKEN
    TOKEN = "tok-456"      # simule un token révoqué -> 401 -> re-login
    return {}
