import os

os.environ.setdefault("JWT_SECRET", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

from onboarding import parse_single_ip, parse_cidr, parse_ip_list, is_duplicate


def test_parse_single_ip():
    assert parse_single_ip("192.168.1.5") == ["192.168.1.5"]
    assert parse_single_ip("garbage") == []


def test_parse_cidr():
    res = parse_cidr("10.0.0.0/30")
    assert len(res) == 2
    assert "10.0.0.1" in res


def test_parse_ip_list_mixed():
    txt = "192.168.1.1\n10.0.0.0/30\n# comment\n"
    res = parse_ip_list(txt)
    assert "192.168.1.1" in res
    assert len(res) == 3


def test_is_duplicate():
    assert is_duplicate(["1.2.3.4"], "1.2.3.4") is True
    assert is_duplicate(["1.2.3.4"], "5.6.7.8") is False