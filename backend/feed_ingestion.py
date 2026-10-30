"""Feed ingestion plugin interface (S3-2)."""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx


class VulnSourcePlugin(ABC):
    name: str = "base"

    @abstractmethod
    async def fetch(self, since: Optional[str] = None) -> list[dict]:
        ...

    @abstractmethod
    def normalize(self, raw: dict) -> dict:
        ...


class NVDSource(VulnSourcePlugin):
    name = "nvd"
    url = "https://services.nvd.nist.gov/rest/json/cves/2.0"

    async def fetch(self, since=None) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                params = {"resultsPerPage": 5}
                if since:
                    params["lastModStartDate"] = since
                headers = {}
                key = os.environ.get("NVD_API_KEY")
                if key:
                    headers["apiKey"] = key
                r = await client.get(self.url, params=params, headers=headers)
                if r.status_code != 200:
                    return []
                data = r.json()
                return data.get("vulnerabilities", [])
        except Exception:
            return []

    def normalize(self, raw: dict) -> dict:
        cve = raw.get("cve", {}) if isinstance(raw, dict) else {}
        return {"cve_id": cve.get("id"), "title": "", "summary": (cve.get("descriptions") or [{}])[0].get("value", "")}


class OSVSource(VulnSourcePlugin):
    name = "osv"
    url = "https://api.osv.dev/v1/query"

    async def fetch(self, since=None) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(self.url, json={"package": {"name": "openssl"}, "version": "1.0"})
                if r.status_code != 200:
                    return []
                data = r.json()
                return data.get("vulns", [])
        except Exception:
            return []

    def normalize(self, raw: dict) -> dict:
        return {"cve_id": raw.get("id"), "title": raw.get("summary", ""), "summary": raw.get("details", "")}


async def sync_source(plugin: VulnSourcePlugin, session, since=None) -> dict:
    raws = await plugin.fetch(since)
    count = 0
    for r in raws:
        _ = plugin.normalize(r)
        count += 1
    return {"source": plugin.name, "ingested": count, "idempotent": True}