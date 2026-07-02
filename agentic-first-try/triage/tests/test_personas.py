from pathlib import Path

PERSONAS = Path("triage/personas")


def test_three_personas_exist():
    for name in ("triage.md", "fix-it-man.md", "stoic-developer.md"):
        assert (PERSONAS / name).is_file()


def test_triage_prompt_names_finish_and_route():
    text = (PERSONAS / "triage.md").read_text().lower()
    assert "finish" in text and "route" in text and "severity" in text


def test_worker_prompts_are_advisory_no_code():
    for name in ("fix-it-man.md", "stoic-developer.md"):
        text = (PERSONAS / name).read_text().lower()
        assert "do not write" in text or "do not modify" in text  # advisory boundary stated
