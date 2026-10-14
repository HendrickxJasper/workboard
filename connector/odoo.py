"""Minimal client for Odoo's External JSON-2 API (Odoo 19+).

    POST {url}/json/2/{model}/{method}
    Authorization: bearer <api key>
    X-Odoo-Database: <db>
    body: {"ids": [...], "context": {...}, <named method arguments>}

The response body is the method's return value as JSON. Errors come back as a
non-2xx status with a JSON body that has at least "name" and "message".
"""

from __future__ import annotations

import httpx
from django.conf import settings


class OdooError(Exception):
    def __init__(self, message, *, status=None, name=""):
        super().__init__(message)
        self.status = status
        self.name = name


class OdooClient:
    def __init__(self, url: str, db: str, api_key: str, *, timeout: float = 30, transport=None):
        if not (url and api_key):
            raise OdooError("Odoo is not configured (ODOO_URL / ODOO_API_KEY).")
        self.url = url.rstrip("/")
        self.db = db
        headers = {"Authorization": f"bearer {api_key}", "Content-Type": "application/json; charset=utf-8"}
        if db:
            headers["X-Odoo-Database"] = db
        self._http = httpx.Client(
            base_url=f"{self.url}/json/2", headers=headers, timeout=timeout, transport=transport
        )

    @classmethod
    def from_settings(cls, **kwargs) -> OdooClient:
        return cls(settings.ODOO_URL, settings.ODOO_DB, settings.ODOO_API_KEY, **kwargs)

    def call(self, model: str, method: str, **params):
        try:
            resp = self._http.post(f"/{model}/{method}", json=params)
        except httpx.HTTPError as exc:
            raise OdooError(f"Odoo unreachable: {exc}") from exc
        if resp.status_code >= 400:
            try:
                data = resp.json()
            except ValueError:
                data = {}
            raise OdooError(
                data.get("message") or resp.text[:300] or f"HTTP {resp.status_code}",
                status=resp.status_code,
                name=data.get("name", ""),
            )
        return resp.json()

    # --- helpers ---------------------------------------------------------------
    def search_read(self, model, domain, fields, *, limit=None, order=None):
        params = {"domain": domain, "fields": fields}
        if limit:
            params["limit"] = limit
        if order:
            params["order"] = order
        return self.call(model, "search_read", **params)

    def create(self, model, vals: dict) -> int:
        ids = self.call(model, "create", vals_list=[vals])
        return ids[0] if isinstance(ids, list) else ids

    def message_post(self, model, res_id: int, body: str, *, note=True):
        return self.call(
            model,
            "message_post",
            ids=[res_id],
            body=body,
            message_type="comment",
            subtype_xmlid="mail.mt_note" if note else "mail.mt_comment",
        )

    def record_url(self, model: str, res_id: int) -> str:
        return f"{self.url}/odoo/{model}/{res_id}"
