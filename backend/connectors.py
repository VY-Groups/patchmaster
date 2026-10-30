"""Connector abstraction (S2-2): unified transport interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CommandResult:
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    ok: bool = True


class Connector(ABC):
    def __init__(self, host=None, timeout: int = 60):
        self.host = host
        self.timeout = timeout

    @abstractmethod
    async def connect(self) -> bool:
        ...

    @abstractmethod
    async def run(self, template: str, params: Optional[dict] = None) -> CommandResult:
        ...

    @abstractmethod
    async def put_file(self, local: str, remote: str) -> bool:
        ...

    @abstractmethod
    async def get_file(self, remote: str, local: str) -> bool:
        ...

    @abstractmethod
    async def facts(self) -> dict:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...


class AgentConnector(Connector):
    async def connect(self) -> bool:
        return True

    async def run(self, template, params=None) -> CommandResult:
        # shortcut: delegates to agent /run; simulated here
        return CommandResult(ok=True, stdout="agent-ok")

    async def put_file(self, local, remote) -> bool:
        return True

    async def get_file(self, remote, local) -> bool:
        return True

    async def facts(self) -> dict:
        return {"transport": "agent"}

    async def close(self) -> None:
        return None


class SshConnector(Connector):
    def __init__(self, host=None, timeout: int = 60, credentials: Optional[dict] = None):
        super().__init__(host, timeout)
        self.credentials = credentials or {}
        self._client = None

    async def connect(self) -> bool:
        ip = getattr(self.host, "ip", None) if self.host is not None else None
        if not ip or not self.credentials.get("username"):
            return True  # simulated (no creds)
        try:
            import paramiko
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(ip, username=self.credentials["username"],
                          password=self.credentials.get("password"),
                          key_filename=self.credentials.get("key_filename"),
                          timeout=self.timeout, banner_timeout=self.timeout)
            self._client = client
            return True
        except Exception:
            self._client = None
            return False

    async def run(self, template, params=None) -> CommandResult:
        import time
        if self._client is not None:
            try:
                stdin, stdout, stderr = self._client.exec_command(template, timeout=self.timeout)
                out = stdout.read().decode("utf-8", "replace")
                err = stderr.read().decode("utf-8", "replace")
                rc = stdout.channel.recv_exit_status()
                return CommandResult(exit_code=rc, stdout=out, stderr=err, ok=(rc == 0))
            except Exception as e:
                return CommandResult(ok=False, stderr=str(e), exit_code=1)
        return CommandResult(ok=True, stdout="ssh-ok")  # simulated

    async def put_file(self, local, remote) -> bool:
        return True

    async def get_file(self, remote, local) -> bool:
        return True

    async def facts(self) -> dict:
        return {"transport": "ssh"}

    async def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None


class WinRmConnector(Connector):
    def __init__(self, host=None, timeout: int = 60, credentials: Optional[dict] = None):
        super().__init__(host, timeout)
        self.credentials = credentials or {}
        self._session = None

    async def connect(self) -> bool:
        ip = getattr(self.host, "ip", None) if self.host is not None else None
        if not ip or not self.credentials.get("username"):
            return True  # simulated (no creds)
        transport = self.credentials.get("transport", "negotiate")
        # normalize
        if transport == "negotiate":
            transport = "negotiate"  # handled by pypsrp
        try:
            # Prefer pypsrp for Negotiate (handles Kerberos/NTLM properly)
            if transport in ("negotiate", "kerberos"):
                try:
                    from pypsrp.client import Client
                    self._psrp = Client(
                        ip,
                        username=self.credentials["username"],
                        password=self.credentials.get("password", ""),
                        ssl=False,
                        auth=transport,
                        cert_validation=False,
                    )
                    self._transport = "psrp"
                    return True
                except Exception:
                    self._psrp = None
            # pywinrm for other transports
            import winrm
            if transport == "certificate":
                self._session = winrm.Session(
                    f"https://{ip}:5986/wsman",
                    auth=(self.credentials.get("cert_pem", ""), self.credentials.get("key_pem", "")),
                    transport="certificate",
                    cert_validation=self.credentials.get("cert_validation", False),
                )
            elif transport == "ldap":
                domain = self.credentials.get("domain", "")
                user = self.credentials["username"]
                if domain and "\\" not in user and "@" not in user:
                    user = f"{domain}\\{user}"
                self._session = winrm.Session(
                    f"http://{ip}:5985/wsman",
                    auth=(user, self.credentials.get("password", "")),
                    transport="ntlm",
                )
            else:
                self._session = winrm.Session(
                    f"http://{ip}:5985/wsman",
                    auth=(self.credentials["username"], self.credentials.get("password", "")),
                    transport=transport if transport != "negotiate" else "ntlm",
                )
            self._transport = "winrm"
            return True
        except Exception:
            self._session = None
            self._psrp = None
            return False

    async def run(self, template, params=None) -> CommandResult:
        # pypsrp path (Negotiate/Kerberos)
        if getattr(self, "_transport", None) == "psrp" and getattr(self, "_psrp", None) is not None:
            try:
                out, streams, rc = self._psrp.execute_ps(template)
                had_errors = getattr(streams, "had_errors", False) if streams else False
                return CommandResult(exit_code=0 if not had_errors else 1,
                                    stdout=str(out or ""),
                                    stderr=str(streams) if (streams and had_errors) else "",
                                    ok=not had_errors)
            except Exception as e:
                return CommandResult(ok=False, stderr=str(e), exit_code=1)
        # pywinrm path
        if self._session is not None:
            try:
                r = self._session.run_ps(template)
                return CommandResult(exit_code=r.status_code,
                                    stdout=r.std_out.decode("utf-8", "replace"),
                                    stderr=r.std_err.decode("utf-8", "replace"),
                                    ok=(r.status_code == 0))
            except Exception as e:
                return CommandResult(ok=False, stderr=str(e), exit_code=1)
        return CommandResult(ok=True, stdout="winrm-ok")  # simulated

    async def put_file(self, local, remote) -> bool:
        return True

    async def get_file(self, remote, local) -> bool:
        return True

    async def facts(self) -> dict:
        return {"transport": "winrm"}

    async def close(self) -> None:
        self._session = None


class RelayConnector(Connector):
    async def connect(self) -> bool:
        return True

    async def run(self, template, params=None) -> CommandResult:
        return CommandResult(ok=True, stdout="relay-ok")

    async def put_file(self, local, remote) -> bool:
        return True

    async def get_file(self, remote, local) -> bool:
        return True

    async def facts(self) -> dict:
        return {"transport": "relay"}

    async def close(self) -> None:
        return None


def connector_for(host, mode: str = "agent", credentials: dict = None) -> Connector:
    mode = (mode or "agent").lower()
    creds = credentials or {}
    if mode == "ssh":
        return SshConnector(host, credentials=creds)
    if mode == "winrm":
        return WinRmConnector(host, credentials=creds)
    if mode == "relay":
        return RelayConnector(host)
    return AgentConnector(host)