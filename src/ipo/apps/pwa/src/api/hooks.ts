// react-query hooks over the GET-only engine API. `useHealth` drives the engine-up/down state
// (the readiness gate + live status); the data hooks feed the screens read-only.

import { useQuery } from '@tanstack/react-query'
import { apiGet } from './client'
import type { CalibrationView, HistoryRow, IPODetail, IPOListRow, Verdict } from './types'

export const useHealth = () =>
  useQuery({
    queryKey: ['health'],
    queryFn: () => apiGet<{ status: string }>('/health'),
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

export const useHistory = () =>
  useQuery({ queryKey: ['history'], queryFn: () => apiGet<HistoryRow[]>('/history') })

export const useCalibration = () =>
  useQuery({ queryKey: ['calibration'], queryFn: () => apiGet<CalibrationView>('/calibration') })
