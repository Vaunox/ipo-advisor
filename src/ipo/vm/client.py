"""App-side VM client (v3 V3-1 step 2) — the local engine's VM-primary fetch, fail-loud.

The LOCAL engine (never the browser) uses this each refresh cycle: fetch a store from the VM,
validate the ``{refreshed_at, data}`` envelope against the shared schema (``vm.models``), and hand
back typed data — or raise :class:`VmUnavailable` so the caller falls back to local.

**Don't trust a 200.** A malformed or truncated body fails to parse/validate and is treated as
unavailable, exactly like a timeout or a connection error — never fed into the app. **The fetch is
the health decision**, re-run each cycle (10 s timeout, 2 retries), so the app self-heals the moment
the VM returns; there is no sticky "VM is down" latch.
"""

from __future__ import annotations

from typing import TypeVar

import requests
from pydantic import ValidationError

from ipo.core.logging import get_logger
from ipo.vm.models import ContextEnvelope, RecordsEnvelope

_log = get_logger("ipo.vm.client")

_Envelope = TypeVar("_Envelope", RecordsEnvelope, ContextEnvelope)

_TIMEOUT_SEC = 10.0  # blueprint: VM request timeout 10s ...
_RETRIES = 2  # ... then 2 retries, then fall back to local


class VmUnavailable(Exception):
    """The VM could not be reached, returned non-200, or returned data that failed validation."""


class VmClient:
    """Fetches records/context from the VM; raises :class:`VmUnavailable` on any failure."""

    def __init__(
        self, base_url: str, *, timeout: float = _TIMEOUT_SEC, retries: int = _RETRIES
    ) -> None:
        """Bind the VM base URL (the app fetches ``{base_url}/records`` etc.) + the fetch budget."""
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._retries = retries

    def fetch_records(self) -> RecordsEnvelope:
        """The record store from the VM, deeply validated — or ``VmUnavailable``."""
        return self._validated("/records", RecordsEnvelope)

    def fetch_context(self) -> ContextEnvelope:
        """The context cache envelope from the VM — or ``VmUnavailable``."""
        return self._validated("/context", ContextEnvelope)

    def _validated(self, path: str, model: type[_Envelope]) -> _Envelope:
        payload = self._get_json(path)
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            # A 200 with the wrong shape is NOT good data — treat it as unavailable, don't trust it.
            raise VmUnavailable(f"{path}: malformed envelope ({exc.error_count()} errors)") from exc

    def _get_json(self, path: str) -> object:
        """GET ``path`` with the retry budget; raise ``VmUnavailable`` if none succeeds."""
        url = f"{self._base}{path}"
        detail = "unknown"
        for _ in range(self._retries + 1):  # 1 attempt + ``retries`` more
            try:
                resp = requests.get(url, timeout=self._timeout)
            except requests.RequestException as exc:  # DNS / connection / timeout
                detail = str(exc)
                continue
            if resp.status_code != 200:
                detail = f"HTTP {resp.status_code}"
                continue
            try:
                return resp.json()
            except ValueError as exc:  # truncated / non-JSON body
                detail = f"non-JSON body: {exc}"
                continue
        raise VmUnavailable(f"{path}: {detail}")
