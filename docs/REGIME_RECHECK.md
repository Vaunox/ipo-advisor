# Cold-flag (-0.3) re-check — READ-ONLY (Phase 6 prereq #2)

*Confirms `market_regime <= -0.3` is a sane prior before it shapes live verdicts. Strictly read-only: nothing is tuned, the config value stays **-0.3**. Not financial advice.*

## Flag rate by candidate threshold

| threshold | all mainboard 2021+ | of which cold | known-cold (skworld) |
|---|---|---|---|
| -0.2 | 22% (N=293) | 68% (N=96) | 66% (N=234) |
| -0.3 **(current)** | 20% (N=293) | 60% (N=96) | 58% (N=234) |
| -0.4 | 15% (N=293) | 45% (N=96) | 48% (N=234) |

## Reading

At the current **-0.3**, the flag fires on **20%** of all mainboard IPOs — a clear minority (not noise, not everything) — and catches **58%** of independently known-cold IPOs (the rest are cold via mild drawdown with a flat/slightly positive 3-month trend, which the flag intentionally does not over-call). Moving to -0.2 flags more broadly; -0.4 only the deepest corrections. **-0.3 sits sensibly between the two and is confirmed as a reasonable prior — left unchanged.**

Re-examine again only if the live flag rate drifts far from this; never tune it to listing outcomes (it is a prior on market state, not a fitted parameter).