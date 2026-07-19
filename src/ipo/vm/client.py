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
from urllib.parse import quote

import requests
from pydantic import ValidationError

from ipo.core.logging import get_logger
from ipo.vm.models import ContextEnvelope, RecordsEnvelope, SeriesEnvelope

_log = get_logger("ipo.vm.client")

_Envelope = TypeVar("_Envelope", RecordsEnvelope, ContextEnvelope, SeriesEnvelope)

_TIMEOUT_SEC = 10.0  # blueprint: VM request timeout 10s ...
_RETRIES = 2  # ... then 2 retries, then fall back to local

# --- on-demand (user-facing) budget, v3-DP DP-3a ---------------------------
#
# The defaults above are sized for the 30-min BACKGROUND cycle, where retrying hard is right: no
# one is waiting, and a missed cycle costs freshness. A detail-page open is the opposite — a person
# is watching — so 10s x 3 attempts (~30s) would hang the UI for half a minute before it could
# honestly say "unavailable". Same client class, different budget, because the tradeoff differs.
#
# Both numbers are pinned against MEASURED latency on the real desktop->VM path rather than picked
# by feel (the unexplained-constant class this project keeps getting bitten by):
#   median 45 ms, min 38 ms, max 1.18 s over 10 runs to the live endpoint.
# The ~1.2s outliers are the 1-vCPU box under keepalive contention (a bounded CPU burn runs every
# 30 min), so the ceiling must clear those comfortably or a healthy VM would be reported down.
ON_DEMAND_TIMEOUT_SEC = 5.0  # ~4.2x the worst observed healthy response (1.18s) — clears a
# keepalive-contended spike, still fails fast enough for a UI.
ON_DEMAND_RETRIES = 1  # one retry absorbs a single transient blip; more attempts serve a
# background job, not a person waiting. Worst case ~10s vs the cycle's ~30s.


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

    def fetch_series(self, ipo_id: str) -> SeriesEnvelope:
        """ONE IPO's banked subscription trajectory (v3-DP DP-3a) — or ``VmUnavailable``.

        Mirrors ``fetch_records`` exactly: same retry budget object, same envelope validation, same
        "don't trust a 200". The ``ipo_id`` is URL-encoded — the VM refuses an unsafe id into an
        empty envelope, but the client should not build a malformed URL to find that out.

        AN IPO WITH NO SERIES IS NOT A FAILURE. The VM answers an empty-but-valid envelope and this
        returns it with ``samples == []``; for months that is the honest, ordinary answer (nothing
        was ever recorded). ``VmUnavailable`` means the VM could not be reached or sent a shape we
        refuse to trust — a *different truth*, and the caller must keep the two apart.
        """
        return self._validated(
            f"/subscription-series?ipo_id={quote(ipo_id, safe='')}", SeriesEnvelope
        )

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
