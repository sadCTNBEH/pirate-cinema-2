"""Advisory/strict policy for the Chromium security patch used by Qt WebEngine."""

from __future__ import annotations

from packaging.version import InvalidVersion, Version


def assess_chromium_security(
    chromium_version: str | None,
    security_patch: str | None,
    minimum_patch: str | None,
    *,
    strict: bool = False,
) -> dict[str, str]:
    """Return a diagnostic status without conflating it with media playback."""
    result = {
        "chromiumVersion": chromium_version or "unavailable",
        "chromiumSecurityPatch": security_patch or "unavailable",
        "minimumChromiumSecurityPatch": minimum_patch or "not configured",
    }
    if not chromium_version or not security_patch:
        result.update(
            status="FAILED",
            message="Qt WebEngine did not report its Chromium version and security patch",
        )
        return result
    if not minimum_patch:
        result.update(status="PASSED", message="Chromium minimum security patch is not configured")
        return result
    try:
        current = Version(security_patch)
        minimum = Version(minimum_patch)
    except InvalidVersion as error:
        result.update(status="FAILED", message=f"Cannot compare Chromium security patch: {error}")
        return result
    if current >= minimum:
        result.update(status="PASSED", message="Chromium security patch meets the configured minimum")
    elif strict:
        result.update(
            status="FAILED",
            message=(
                f"Chromium {chromium_version} security patch {security_patch} is below "
                f"the required minimum {minimum_patch} (strict mode)"
            ),
        )
    else:
        result.update(
            status="WARNING",
            message=(
                f"Chromium {chromium_version} security patch {security_patch} is below "
                f"the configured minimum {minimum_patch}"
            ),
        )
    return result


def apply_chromium_security_policy(
    payload: dict,
    chromium_version: str | None,
    security_patch: str | None,
    minimum_patch: str | None,
    *,
    strict: bool = False,
) -> dict:
    """Attach version diagnostics, failing only security in strict mode.

    A pre-existing functional smoke failure is preserved regardless of the
    security result. Missing/unusable WebEngine version data fails a healthy
    playback result because the engine itself could not be verified.
    """
    security = assess_chromium_security(
        chromium_version, security_patch, minimum_patch, strict=strict,
    )
    payload.update(security)
    if security["status"] == "FAILED" and payload.get("ok"):
        payload["ok"] = False
        payload.setdefault("error", security["message"])
    return payload
