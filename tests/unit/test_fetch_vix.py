"""fetch_vix.py date mapping (low L2): a VIX close is filed under its IST trading day.

The bug: ``_fetch_year`` used naive ``datetime.fromtimestamp(stamp).date()``, so on a machine
west of IST (the Americas) a bar whose 09:15–15:30 IST session sits in the previous local
evening was filed a day early — shifting which IPOs get the weight-0 cold-market flag
(``VixSeries`` keys the CSV date to IST IPO close-dates). ``_ist_date`` converts in the fixed
+5:30 IST zone, so the map is identical on any runner. (UTC is coincidentally fine — the session
is 03:45–10:00 UTC, same calendar day — so this bites Americas machines, not the UTC CI runner.)
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
import time
from pathlib import Path
from types import ModuleType
from zoneinfo import ZoneInfo

from ipo.core.constants import IST


def _load_fetch_vix() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "fetch_vix.py"
    spec = importlib.util.spec_from_file_location("fetch_vix", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_FV = _load_fetch_vix()

# An India VIX bar for Tue 2024-01-02, stamped at the 09:15 IST session open.
_EPOCH = int(dt.datetime(2024, 1, 2, 9, 15, tzinfo=IST).timestamp())


def test_ist_date_maps_to_the_ist_trading_day() -> None:
    assert _FV._ist_date(_EPOCH) == dt.date(2024, 1, 2)


def test_a_naive_local_read_would_mis_date_it_west_of_ist() -> None:
    # The bug being fixed: in a US zone the same instant is the PREVIOUS calendar day — exactly what
    # naive fromtimestamp() would have filed on an Americas machine.
    us = dt.datetime.fromtimestamp(_EPOCH, tz=ZoneInfo("America/Los_Angeles")).date()
    assert us == dt.date(2024, 1, 1)  # off by one
    assert _FV._ist_date(_EPOCH) != us  # the fix does not follow the local zone


def test_ist_date_is_stable_regardless_of_the_runners_local_tz() -> None:
    # `_ist_date` passes tz=IST explicitly, so it never consults the process zone. Prove it by
    # forcing a US local zone (Unix only — Windows has no tzset) and re-asserting the same result.
    if not hasattr(time, "tzset"):
        assert _FV._ist_date(_EPOCH) == dt.date(2024, 1, 2)  # the tz-munge can't run here
        return
    saved = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "America/Los_Angeles"
        time.tzset()
        assert _FV._ist_date(_EPOCH) == dt.date(2024, 1, 2)  # unchanged despite a US local tz
    finally:
        if saved is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = saved
        time.tzset()
