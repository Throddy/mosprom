import type { EventStatus, EventView, EventsQuery } from '../api/types.ts'

// Фильтры журнала по CONTRACT.md, раздел 6: type, camera_id, zone_id, status, from, to
export interface JournalFilters {
  type?: string
  camera_id?: string
  zone_id?: string
  status?: string
  from?: number
  to?: number
}

export interface JournalState extends JournalFilters {
  page: number
  limit: number
  // id события, открытого в деталях
  event?: string
}

export const LIMITS = [25, 50, 100]
export const DEFAULT_LIMIT = 50
export const STATUSES: EventStatus[] = ['new', 'confirmed', 'false', 'forwarded']

const TEXT_KEYS = ['type', 'camera_id', 'zone_id', 'status'] as const

function int(value: string | null): number | undefined {
  if (value === null || value.trim() === '') return undefined
  const n = Number(value)
  return Number.isFinite(n) ? Math.trunc(n) : undefined
}

export function parseJournal(params: URLSearchParams): JournalState {
  const state: JournalState = { page: 1, limit: DEFAULT_LIMIT }
  for (const key of TEXT_KEYS) {
    const v = params.get(key)
    if (v) state[key] = v
  }
  state.from = int(params.get('from'))
  state.to = int(params.get('to'))
  const page = int(params.get('page'))
  if (page !== undefined && page >= 1) state.page = page
  const limit = int(params.get('limit'))
  if (limit !== undefined && LIMITS.includes(limit)) state.limit = limit
  const event = params.get('event')
  if (event) state.event = event
  return state
}

// Обратно в URL; значения по умолчанию не пишутся
export function journalParams(state: JournalState): URLSearchParams {
  const params = new URLSearchParams()
  for (const key of TEXT_KEYS) {
    const v = state[key]
    if (v) params.set(key, v)
  }
  if (state.from !== undefined) params.set('from', String(state.from))
  if (state.to !== undefined) params.set('to', String(state.to))
  if (state.page > 1) params.set('page', String(state.page))
  if (state.limit !== DEFAULT_LIMIT) params.set('limit', String(state.limit))
  if (state.event) params.set('event', state.event)
  return params
}

export function toQuery(state: JournalState): EventsQuery {
  return {
    type: state.type,
    camera_id: state.camera_id,
    zone_id: state.zone_id,
    status: state.status,
    from: state.from,
    to: state.to,
    limit: state.limit,
    offset: (state.page - 1) * state.limit,
  }
}

export function rangeError(state: JournalFilters): string | null {
  if (state.from !== undefined && state.to !== undefined && state.from > state.to) {
    return 'Начало периода позже конца'
  }
  return null
}

export function hasFilters(state: JournalFilters): boolean {
  return TEXT_KEYS.some((k) => state[k]) || state.from !== undefined || state.to !== undefined
}

// Совпадает ли событие с фильтрами так же, как в GET /api/events: from и to по ts_confirm включительно
export function matchesFilters(e: EventView, f: JournalFilters): boolean {
  if (f.type && e.type !== f.type) return false
  if (f.camera_id && e.camera_id !== f.camera_id) return false
  if (f.zone_id && e.zone_id !== f.zone_id) return false
  if (f.status && e.status !== f.status) return false
  if (f.from !== undefined && e.ts_confirm < f.from) return false
  if (f.to !== undefined && e.ts_confirm > f.to) return false
  return true
}

export function pageCount(total: number, limit: number): number {
  return Math.max(1, Math.ceil(total / limit))
}
