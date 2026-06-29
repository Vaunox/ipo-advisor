"""Secrets access (Ground Rule 2).

Secrets NEVER live in code or config. They are read at runtime from environment
variables (and, optionally, files in a gitignored ``secrets/`` directory, the
docker-secrets convention). Values returned here must never be logged.

Only the optional push-notification keys — and ``KITE_*`` *if and only if* Kite is
ever wired as a market-data source — flow through this module. No order-placement
credential exists, because the system places no orders.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path


class MissingSecretError(RuntimeError):
    """Raised when a required secret is absent from every provider."""


class SecretProvider:
    """Resolves secrets from environment variables, then an optional secrets dir.

    Args:
        environ: Environment mapping (injectable for tests); defaults to ``os.environ``.
        secrets_dir: Optional directory of files named after each secret. A file's
            contents (stripped) are used when the env var is absent.
    """

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        secrets_dir: Path | None = None,
    ) -> None:
        """Initialize the provider from an env mapping and optional secrets dir."""
        self._environ = os.environ if environ is None else environ
        self._secrets_dir = secrets_dir

    def get(self, name: str, *, default: str | None = None) -> str | None:
        """Return the secret value, or ``default`` if it is not configured anywhere."""
        if name in self._environ:
            return self._environ[name]
        if self._secrets_dir is not None:
            candidate = self._secrets_dir / name
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8").strip()
        return default

    def require(self, name: str) -> str:
        """Return the secret value, or raise ``MissingSecretError`` if it is absent."""
        value = self.get(name)
        if value is None:
            # Note: the name is safe to log; the value is never logged.
            raise MissingSecretError(f"Required secret '{name}' is not configured")
        return value
