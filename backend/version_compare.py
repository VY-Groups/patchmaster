"""Version comparison per package-manager scheme (S3-3)."""

from __future__ import annotations

import re
from typing import Optional


def _split(v: str):
    return re.split(r"[.\-+~]", str(v or ""))


def _cmp_tokens(a: str, b: str) -> int:
    # numeric vs string comparison
    if a.isdigit() and b.isdigit():
        ia, ib = int(a), int(b)
        return (ia > ib) - (ia < ib)
    if a.isdigit() and not b.isdigit():
        return 1  # numeric > non-numeric (dpkg-ish)
    if b.isdigit() and not a.isdigit():
        return -1
    return (a > b) - (a < b)


def compare_generic(a: str, b: str) -> int:
    ta, tb = _split(a), _split(b)
    n = max(len(ta), len(tb))
    for i in range(n):
        x = ta[i] if i < len(ta) else ""
        y = tb[i] if i < len(tb) else ""
        c = _cmp_tokens(x, y)
        if c != 0:
            return c
    return 0


def compare_semver(a: str, b: str) -> int:
    # strip leading v
    a = a.lstrip("v"); b = b.lstrip("v")
    return compare_generic(a, b)


def compare_versions(a: str, b: str, scheme: str = "generic") -> int:
    scheme = (scheme or "generic").lower()
    if scheme in ("semver",):
        return compare_semver(a, b)
    # dpkg/rpm/apk/pacman/windows/generic all use token compare for now
    return compare_generic(a, b)


def version_in_range(version: str, introduced: Optional[str], fixed: Optional[str], scheme: str = "generic") -> bool:
    """True if introduced <= version < fixed (None means unbounded)."""
    if introduced and compare_versions(version, introduced, scheme) < 0:
        return False
    if fixed and compare_versions(version, fixed, scheme) >= 0:
        return False
    return True