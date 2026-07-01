import type { VerdictType } from './api/types'

// Verdict → presentation metadata (matches the comp). `cls` selects the token color set;
// `rank` orders verdict-strength sorting (APPLY strongest).
export const VMETA: Record<VerdictType, { cls: string; label: string; rank: number }> = {
  APPLY: { cls: 'apply', label: 'APPLY', rank: 0 },
  MARGINAL: { cls: 'marginal', label: 'MARGINAL', rank: 1 },
  SKIP: { cls: 'skip', label: 'SKIP', rank: 2 },
  INSUFFICIENT_SIGNAL: { cls: 'insuf', label: 'INSUFFICIENT', rank: 3 },
}

export const isKillFlag = (killFlags: string[]): boolean => killFlags.length > 0
