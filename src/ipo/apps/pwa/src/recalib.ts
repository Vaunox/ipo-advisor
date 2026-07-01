// Recalibration count — derived, matching the comp: the initial gate-passing fit (Q4 2024) plus
// one per quarter since (Phase 8 recalibrates quarterly). Increments on its own as real time
// crosses each quarter. In the real app this would come from the calibrator's version history.
export function recalibrationCount(now: Date = new Date()): number {
  const start = new Date(2024, 9, 1) // Oct 2024
  const q =
    (now.getFullYear() - start.getFullYear()) * 4 +
    (Math.floor(now.getMonth() / 3) - Math.floor(start.getMonth() / 3))
  return 1 + Math.max(0, q)
}
