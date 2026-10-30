"""Asset onboarding helpers (S2-4)."""

from __future__ import annotations

import ipaddress
from typing import Iterable, List


def parse_single_ip(value: str) -> List[str]:
    value = (value or "").strip()
    if not value:
        return []
    try:
        ip = ipaddress.ip_address(value)
        return [str(ip)]
    except ValueError:
        return []


def parse_cidr(value: str) -> List[str]:
    value = (value or "").strip()
    if not value:
        return []
    try:
        net = ipaddress.ip_network(value, strict=False)
        return [str(ip) for ip in net.hosts()]
    except ValueError:
        return []


def parse_ip_list(text: str) -> List[str]:
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "/" in line:
            out.extend(parse_cidr(line))
        else:
            out.extend(parse_single_ip(line))
    return list(dict.fromkeys(out))


def is_duplicate(existing_ips: Iterable[str], candidate: str) -> bool:
    return candidate in set(existing_ips or [])