"""Scoring-path guard — a PRECISE git-path proxy for 'nothing may reach the feature vector'.

Part I rule 1: no v3 change may alter the scorer, calibrator, feature construction, or probability.
The real invariant is *reachability of the feature vector*; this is a cheap proxy for it — it fails
if a change touches the model / calibration / features / core computation, ``models/``, or
``config/``. It is a proxy, not the invariant: the definitive check is behavioural (dump verdicts on
the branch vs the base and assert ``MAX|Δprob| = 0.0`` across all IPOs). Run this first; on a
failure, either revert or prove byte-identical verdicts and allowlist the file with a reason.

**Allowlisted — ``src/ipo/core/logging.py``.** It lives under ``core/`` but is a *write-only sink*:
it emits structured logs out of the process and nothing reads them back — there is no import path
from it to ``features/build.py``. When it changes, verdicts are proven byte-identical (0.0).
Excluding it keeps the proxy precise: a guard that fires on a file it cannot possibly break trains
you to
override it by reflex — and then you override the next, real firing too. Add to ``_ALLOWED`` only a
file genuinely unreachable from feature construction, with a reason.

Usage:  python scripts/check_scoring_path.py [base_ref]   # base_ref defaults to 'main'
Exit 0 = clean; exit 1 = a protected (non-allowlisted) file changed vs the base.
"""

from __future__ import annotations

import subprocess
import sys

# Prefixes whose contents compute or configure the verdict/probability (the "scoring path").
_PROTECTED = (
    "src/ipo/model/",
    "src/ipo/calibration/",
    "src/ipo/features/",
    "src/ipo/core/",
    "models/",
    "config/",
)

# Files under a protected prefix that are provably unreachable from feature construction. Each entry
# is a deliberate, reviewed exception — see the module docstring for the bar it must clear.
_ALLOWED = frozenset(
    {
        "src/ipo/core/logging.py",  # write-only sink; nothing reads logs back into build_features
    }
)


def changed_files(base: str) -> list[str]:
    """Files changed on HEAD since it diverged from ``base`` (merge-base diff)."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def offending(files: list[str]) -> list[str]:
    """Protected files that changed and are not allowlisted."""
    return [f for f in files if f.startswith(_PROTECTED) and f not in _ALLOWED]


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "main"
    hits = offending(changed_files(base))
    if hits:
        print(f"SCORING-PATH GUARD: FAILED — protected file(s) changed vs {base}:")
        for path in hits:
            print(f"  - {path}")
        print(
            "\nThe scoring path may only change with proof. Dump verdicts on this branch vs the\n"
            "base and confirm MAX|Δprob| = 0.0 across all IPOs — then either revert, or (if the\n"
            "file is genuinely write-only / unreachable from features) allowlist it in\n"
            "_ALLOWED with a reason. Do NOT allowlist to silence a real change."
        )
        raise SystemExit(1)
    allowed = ", ".join(sorted(_ALLOWED)) or "(none)"
    print(f"SCORING-PATH GUARD: OK — no protected file changed vs {base} (allowlisted: {allowed}).")


if __name__ == "__main__":
    main()
