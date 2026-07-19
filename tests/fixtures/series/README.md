# Synthetic subscription-series fixtures (v3-DP DP-2, reused by DP-3)

Static JSON in the exact on-disk shape `SubscriptionSeriesStore` writes — one file per IPO, a list
of stored rows.

**The precedent this follows.** `tests/fixtures/` is pre-existing and already holds seven data files
(`nse_active_category_sample.json`, `nse_past_issues.json`, `retail_allotment_ratios.json`,
`chittorgarh_recent_ipos.html`, …) loaded by `Path` from Python tests — see
`tests/unit/test_nse.py` and `tests/unit/test_allotment.py`. **The `series/` subdirectory is new;
the loading pattern is not.** A first draft made this an importable Python module instead, which
mypy rejected (reachable under two module names, since `tests/` is deliberately not a package) —
the data-file convention is both the established one and the one that type-checks.

**On reuse by DP-3, stated honestly:** no fixture in this directory is read by the frontend today —
the `node --test` suites live beside their sources (`src/ipo/apps/*/src/*.test.ts`) and use inline
data. JSON was chosen partly *so that* DP-3 **can** read these bytes rather than duplicating the
shapes, since it could never import a Python module. That is an intention, not an existing
precedent, and DP-3 has to actually do it for the reuse to be real.

## Why synthetic

The real store holds one live IPO mid-book. The shapes the route and the graph must handle cannot
be waited for — a completed multi-day trajectory, a fetch-gap, a never-recorded IPO — and DP-3 has
to render its three honest display states before any real curve exists.

## The shapes, and the truth each one pins

| File | Samples | Pins |
|---|---|---|
| `fixture-testco.json` | 48 | A full open→close trajectory **including a weekend flat stretch**. The normal case. |
| `fixture-mockon.json` | 1 | A single lonely sample — an IPO recorded once, exactly as DP-1 was when deployed mid-book. Sparse is not broken. |
| `fixture-gapco.json` | 36 | The same trajectory with cycles 12–23 **missing**: a fetch-failure window. DP-1 banks *nothing* on a failed fetch, so this gap is real absence. DP-3 must draw a **broken line**, never an interpolated bridge that invents readings the recorder deliberately refused to fabricate. |
| `fixture-corrupt.json` | — | A **truncated** file — a valid prefix cut mid-object, which is what a torn write actually looks like (not random bytes). For a REAL id the route must answer empty **and log a warning**: on the wire a corrupt series and a never-recorded one are identical, so without the log a genuine VM fault is indistinguishable from honest absence. |
| *(no file)* | — | `fixture-neverrec` — **never recorded**, the months-long common case and the History-page case. Absence is the fixture; it must read as "not recorded", never as a failure. |

The flat stretch is signal, not filler: across the weekend the multiples stay put **and** NSE's own
`source_update_time` stops advancing, which is what distinguishes "the book did not move" from "our
fetch stalled". That distinction was validated on the very first genuinely banked sample, where a
Sunday capture correctly carried a Friday-17:00 book.

## Obviously fake, and structurally unservable in production

Every id is prefixed `fixture-` with TESTCO/MOCKON-style names, so a fixture curve can never be
mistaken for a real IPO's — the same rule the pre-`.exe` UI QA fixtures follow.

These cannot reach production by construction, not by a flag:

* `tests/` is not in `operations/README.md`'s scp file-list, so nothing here is copied to the VM.
* The VM route reads **only** its `data_dir`. The systemd unit pins `--data-dir /opt/ipo/data`, so
  a fixture is served only if a caller points `data_dir` at this tree — which is what the tests do
  and what the unit cannot do.
* PyInstaller bundles `src/` only, so no fixture reaches the shipped `.exe`.

## Regenerating

They are committed data, not build output — edit them directly, or regenerate with the same shapes
if the stored row schema changes (`schema_version` bump). Keep the four shapes; they are the test
matrix, not examples.
