"""Client minimal de la couche REST de Mercator (lecture seule).

Authentification : POST /api/login {login, password} -> {access_token}
Lecture          : GET  /api/certificates?include=logicalServers,applications
(les listes ne sont pas paginées, cf. APIController::indexResource)
"""
import asyncio

import httpx


class MercatorError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class MercatorClient:
    def __init__(self, base_url: str, login: str, password: str,
                 verify: bool = True, timeout: float = 30.0):
        self.base = base_url.rstrip("/")
        self.login = login
        self.password = password
        self.verify = verify
        self.timeout = timeout
        self._token: str | None = None
        self._lock = asyncio.Lock()

    async def _authenticate(self, client: httpx.AsyncClient) -> None:
        if not self.login or not self.password:
            raise MercatorError("MERCATOR_LOGIN / MERCATOR_PASSWORD non configurés", 500)
        r = await client.post(
            f"{self.base}/api/login",
            json={"login": self.login, "password": self.password},
            headers={"Accept": "application/json"},
        )
        if r.status_code != 200:
            raise MercatorError(
                f"Échec d'authentification Mercator (HTTP {r.status_code})", 502)
        token = r.json().get("access_token")
        if not token:
            raise MercatorError("Réponse de login Mercator sans access_token", 502)
        self._token = token

    async def get(self, path: str, params: dict | None = None):
        try:
            async with httpx.AsyncClient(verify=self.verify, timeout=self.timeout) as client:
                async with self._lock:
                    if not self._token:
                        await self._authenticate(client)
                for attempt in (1, 2):
                    r = await client.get(
                        f"{self.base}{path}", params=params,
                        headers={"Accept": "application/json",
                                 "Authorization": f"Bearer {self._token}"},
                    )
                    if r.status_code == 401 and attempt == 1:
                        # token expiré / révoqué : on se reconnecte une fois
                        async with self._lock:
                            await self._authenticate(client)
                        continue
                    break
        except httpx.HTTPError as e:
            raise MercatorError(f"Mercator injoignable : {e.__class__.__name__}", 502) from e

        if r.status_code == 403:
            raise MercatorError(
                "Accès refusé par Mercator (HTTP 403) : le compte de service doit avoir "
                "le droit certificate_access", 502)
        if r.status_code != 200:
            raise MercatorError(f"Mercator a répondu HTTP {r.status_code} sur {path}", 502)
        data = r.json()
        # selon la ressource, tableau brut ou enveloppe {"data": [...]}
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data

    async def certificates(self) -> list[dict]:
        data = await self.get(
            "/api/certificates", {"include": "logicalServers,applications"})
        if not isinstance(data, list):
            raise MercatorError("Format inattendu pour /api/certificates", 502)
        return data
