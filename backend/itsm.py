"""ITSM connectors (P2): ServiceNow/Jira/Motadata (HTTP-based)."""

from __future__ import annotations

import os
from typing import Any

import httpx


class ITSMConnector:
    name = "base"

    def __init__(self, base_url: str = "", token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = token

    async def create_change(self, title: str, description: str, evidence_ref: str = "") -> dict:
        return {"ok": False, "reason": "not implemented", "connector": self.name}

    async def attach_evidence(self, change_id: str, evidence_ref: str) -> dict:
        return {"ok": False, "reason": "not implemented", "connector": self.name}


class ServiceNowConnector(ITSMConnector):
    name = "servicenow"

    async def create_change(self, title, description, evidence_ref=""):
        if not self.base_url:
            return {"ok": False, "reason": "no base_url", "connector": self.name}
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.post(f"{self.base_url}/api/now/table/change_request",
                                 json={"short_description": title, "description": description},
                                 headers={"Authorization": f"Bearer {self.token}"})
                return {"ok": r.status_code < 300, "status": r.status_code, "connector": self.name}
        except Exception as e:
            return {"ok": False, "reason": str(e), "connector": self.name}


class JiraConnector(ITSMConnector):
    name = "jira"

    async def create_change(self, title, description, evidence_ref=""):
        if not self.base_url:
            return {"ok": False, "reason": "no base_url", "connector": self.name}
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.post(f"{self.base_url}/rest/api/3/issue",
                                 json={"fields": {"summary": title, "description": description, "issuetype": {"name": "Task"}}},
                                 headers={"Authorization": f"Bearer {self.token}"})
                return {"ok": r.status_code < 300, "status": r.status_code, "connector": self.name}
        except Exception as e:
            return {"ok": False, "reason": str(e), "connector": self.name}


class MotadataConnector(ITSMConnector):
    name = "motadata"


def get_connector(name: str, base_url: str = "", token: str = "") -> ITSMConnector:
    cls = {"servicenow": ServiceNowConnector, "jira": JiraConnector,
           "motadata": MotadataConnector}.get(name, ITSMConnector)
    return cls(base_url=base_url, token=token)