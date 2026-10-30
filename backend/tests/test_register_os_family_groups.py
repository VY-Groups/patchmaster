"""Registration must map every OS family to a group (S0-8 fleet regression).

OS_FAMILY_GROUPS is indexed by _detect_os_family()'s return value; a missing
key raises KeyError AFTER the host row is created, so the register endpoint
500s and the agent never receives its token (seen with the first Alpine
container: host created, agent stuck in a 401 re-register loop).
"""

from api.register_v2 import OS_FAMILY_GROUPS, _detect_os_family  # noqa: E402


# Every string _detect_os_family can return for a non-empty input.
ALL_FAMILIES = [
    "Windows Server 2022",
    "Debian GNU/Linux",
    "Ubuntu",
    "Rocky Linux",
    "FreeBSD",
    "Arch Linux",
    "Alpine Linux",
    "openSUSE Leap",
    "Solaris",
    "HP-UX",
    "AIX",
    "Plan 9",
]


def test_detect_os_family_returns_only_known_families():
    families = {_detect_os_family(name) for name in ALL_FAMILIES}
    assert families == set(OS_FAMILY_GROUPS), (
        f"_detect_os_family returned {families - set(OS_FAMILY_GROUPS)} "
        "with no OS_FAMILY_GROUPS entry -> registration would 500"
    )


def test_newly_mapped_families_have_distinct_group_names():
    names = [group for group, _desc in OS_FAMILY_GROUPS.values()]
    assert len(names) == len(set(names)), "OS family group names must be unique"
    for family in ("alpine", "arch", "opensuse"):
        assert family in OS_FAMILY_GROUPS
