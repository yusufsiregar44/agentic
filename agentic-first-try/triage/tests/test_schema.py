from triage.schema import validate_verdict


def _ok():
    return {
        "type": "bug", "severity": "high", "route": "bug",
        "is_duplicate": {"likely": False, "of": None},
        "suspected_area": "auth/login.py",
        "findings": "read login.py; no encoding guard", "comment": "Triage: ...",
        "labels": ["bug", "severity:high"],
    }


def test_valid_verdict_has_no_errors():
    assert validate_verdict(_ok()) == []


def test_bad_enum_values_reported():
    v = _ok(); v["type"] = "feature"; v["severity"] = "urgent"; v["route"] = "maybe"
    errors = validate_verdict(v)
    assert any("type" in e for e in errors)
    assert any("severity" in e for e in errors)
    assert any("route" in e for e in errors)


def test_missing_comment_reported():
    v = _ok(); v["comment"] = "   "
    assert any("comment" in e for e in validate_verdict(v))
