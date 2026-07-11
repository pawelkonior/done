from __future__ import annotations

import hmac
import os
from dataclasses import dataclass


class AccessConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ApiAccessSettings:
    """Single-user deployment boundary until an external IdP is connected.

    Demo mode may run without a token on a developer machine. Live commerce is
    never allowed to boot a public API: a high-entropy bearer token is required.
    """

    enabled: bool
    token: str | None

    @classmethod
    def from_env(cls, *, commerce_mode: str) -> "ApiAccessSettings":
        raw = os.getenv("DONE_API_AUTH_ENABLED")
        if raw is None:
            enabled = commerce_mode == "live"
        else:
            normalized = raw.strip().casefold()
            if normalized in {"1", "true", "yes", "on"}:
                enabled = True
            elif normalized in {"0", "false", "no", "off"}:
                enabled = False
            else:
                raise AccessConfigurationError(
                    "DONE_API_AUTH_ENABLED must be a boolean"
                )
        token = (os.getenv("DONE_API_AUTH_TOKEN") or "").strip() or None
        if commerce_mode == "live" and not enabled:
            raise AccessConfigurationError("Live commerce requires API authentication")
        if enabled and (token is None or len(token) < 32):
            raise AccessConfigurationError(
                "DONE_API_AUTH_TOKEN must contain at least 32 characters"
            )
        return cls(enabled=enabled, token=token)

    def accepts(self, authorization: str | None) -> bool:
        if not self.enabled:
            return True
        if self.token is None or authorization is None:
            return False
        scheme, separator, supplied = authorization.partition(" ")
        if separator != " " or scheme.casefold() != "bearer" or not supplied:
            return False
        return hmac.compare_digest(supplied, self.token)


__all__ = ["AccessConfigurationError", "ApiAccessSettings"]
