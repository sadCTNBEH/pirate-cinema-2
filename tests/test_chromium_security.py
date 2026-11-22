from backend.infrastructure.chromium_security import (
    apply_chromium_security_policy,
    assess_chromium_security,
)


MINIMUM = "155.0.8059.85"


def test_old_chromium_is_warning_by_default() -> None:
    result = assess_chromium_security("102.0.5005.177", "108.0.5359.94", MINIMUM)
    assert result["status"] == "WARNING"
    assert "102.0.5005.177" in result["message"]
    assert MINIMUM in result["message"]


def test_old_chromium_fails_in_strict_mode() -> None:
    result = assess_chromium_security(
        "140.0.7339.264", "151.0.7922.71", MINIMUM, strict=True,
    )
    assert result["status"] == "FAILED"
    assert "strict mode" in result["message"]


def test_current_chromium_passes() -> None:
    result = assess_chromium_security("140.0.7339.264", MINIMUM, MINIMUM)
    assert result["status"] == "PASSED"


def test_missing_webengine_version_fails_even_in_advisory_mode() -> None:
    result = assess_chromium_security(None, None, MINIMUM)
    assert result["status"] == "FAILED"


def test_webengine_failure_remains_independent_of_security_policy() -> None:
    playback = {"ok": False, "error": "H.264 playback failed"}
    result = apply_chromium_security_policy(
        playback, "102.0.5005.177", "108.0.5359.94", MINIMUM,
    )
    assert result["status"] == "WARNING"
    assert result["ok"] is False
    assert result["error"] == "H.264 playback failed"


def test_missing_webengine_fails_playback_even_in_advisory_mode() -> None:
    result = apply_chromium_security_policy({"ok": True}, None, None, MINIMUM)
    assert result["status"] == "FAILED"
    assert result["ok"] is False
