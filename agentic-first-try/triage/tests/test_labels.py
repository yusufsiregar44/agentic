from triage.labels import validate_labels, ALLOWED


def test_known_labels_accepted():
    accepted, rejected = validate_labels(["bug", "severity:high"])
    assert accepted == ["bug", "severity:high"]
    assert rejected == []


def test_unknown_labels_rejected_not_created():
    accepted, rejected = validate_labels(["bug", "URGENT!!", "high-severity"])
    assert accepted == ["bug"]
    assert rejected == ["URGENT!!", "high-severity"]


def test_allowlist_has_no_area_labels():
    assert not any(name.startswith("area:") for name in ALLOWED)
