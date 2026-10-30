import os

os.environ.setdefault("JWT_SECRET", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

from version_compare import compare_versions, version_in_range


def test_basic():
    assert compare_versions("1.2.3", "1.2.4") < 0
    assert compare_versions("1.2.3", "1.2.3") == 0
    assert compare_versions("2.0.0", "1.9.9") > 0


def test_range():
    assert version_in_range("1.2.3", "1.0.0", "1.3.0") is True
    assert version_in_range("1.3.0", "1.0.0", "1.3.0") is False
    assert version_in_range("0.9.0", "1.0.0", "1.3.0") is False
    assert version_in_range("5.0.0", None, "6.0.0") is True


def test_semver():
    assert compare_versions("v1.2.3", "v1.2.4", scheme="semver") < 0