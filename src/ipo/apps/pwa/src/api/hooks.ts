// react-query hooks over the GET-only engine API. `useHealth` drives the engine-up/down state
// (the readiness gate + live status); the data hooks feed the screens read-only.

import { useQuery } from '@tanstack/react-query'
import { apiGet } from './client'
import type {
  AllotmentView,
  CalibrationView,
  HistoryRow,
  IPODetail,
  IPOListRow,
  IpoContextView,
  StatusView,
  Verdict,
  VerdictTransition,
} from './types'

export const useHealth = () =>
  useQuery({
    queryKey: ['health'],
    queryFn: () => apiGet<{ status: string }>('/health'),
    refetchInterval: 5000,
    retry: false,
  })

// Live-ingest freshness (v3 BUG 1 / Defect 2). Polled on the health cadence so the "Updated …" chip
// tracks the last *successful* NSE pull closely (it advances only when a real fetch lands).
export const useStatus = () =>
  useQuery({
    queryKey: ['status'],
    queryFn: () => apiGet<StatusView>('/status'),
    refetchInterval: 5000,
    retry: false,
  })

export const useVerdicts = () =>
  useQuery({ queryKey: ['ipos'], queryFn: () => apiGet<Verdict[]>('/ipos') })

export const useBoard = () =>
  useQuery({ queryKey: ['board'], queryFn: () => apiGet<IPOListRow[]>('/board') })

export const useIpo = (id: string | null) =>
  useQuery({
    queryKey: ['ipo', id],
    queryFn: () => apiGet<IPODetail>(`/ipo/${id}`),
    enabled: !!id,
  })

export const useHistory = (costs?: { stt: number; dp: number; oth: number }) =>
  useQuery({
    queryKey: ['history', costs?.stt, costs?.dp, costs?.oth],
    queryFn: () =>
      apiGet<HistoryRow[]>(
        costs ? `/history?stt=${costs.stt}&dp=${costs.dp}&oth=${costs.oth}` : '/history',
      ),
  })

export const useCalibration = () =>
  useQuery({ queryKey: ['calibration'], queryFn: () => apiGet<CalibrationView>('/calibration') })

// Allotment tab (v3 V3-6) — display-only registrar cache. Read-only; degrades to available=false
// when no cache is loaded (the tab says so). Never a scoring input.
export const useAllotment = () =>
  useQuery({ queryKey: ['allotment'], queryFn: () => apiGet<AllotmentView>('/allotment') })

// One IPO's display-only Upstox context (v3 V3-5: the RHP link). Read-only; never a scoring input.
export const useIpoContext = (id: string | null) =>
  useQuery({
    queryKey: ['context', id],
    queryFn: () => apiGet<IpoContextView>(`/context/${id}`),
    enabled: !!id,
  })

export const useTransitions = () =>
  useQuery({
    queryKey: ['transitions'],
    queryFn: () => apiGet<VerdictTransition[]>('/transitions'),
  })

export const useTransitionsFor = (id: string | null) =>
  useQuery({
    queryKey: ['transitions', id],
    queryFn: () => apiGet<VerdictTransition[]>(`/transitions/${id}`),
    enabled: !!id,
  })
