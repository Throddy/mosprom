import type { EventStatus, EventView, WsMessage } from '../api/types.ts'

// Лента хранит события по id: повторный приход того же события заменяет запись, а не дублирует её
export type FeedEvents = Record<string, EventView>

export const FEED_LIMIT = 200

const SEVERITY_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2 }

export const SEVERITY_LABEL: Record<string, string> = {
  critical: 'Критично',
  high: 'Высокая',
  medium: 'Средняя',
}

export const STATUS_LABEL: Record<EventStatus, string> = {
  new: 'Новое',
  confirmed: 'Подтверждено',
  false: 'Ложное',
  forwarded: 'Передано мастеру',
}

export const ACTIONS: EventStatus[] = ['confirmed', 'false', 'forwarded']

export function upsert(feed: FeedEvents, events: EventView[]): FeedEvents {
  if (events.length === 0) return feed
  const next = { ...feed }
  for (const e of events) next[e.id] = e
  return prune(next)
}

// event_new добавляет событие. event_update меняет только известное событие:
// неизвестные придут при следующей синхронизации через GET /api/events
export function applyMessage(feed: FeedEvents, msg: WsMessage): FeedEvents {
  if (msg.kind === 'event_update' && !(msg.event.id in feed)) return feed
  return upsert(feed, [msg.event])
}

// Критичные первыми, внутри уровня новые по ts_confirm первыми
export function compareEvents(a: EventView, b: EventView): number {
  const ra = SEVERITY_RANK[a.severity] ?? 99
  const rb = SEVERITY_RANK[b.severity] ?? 99
  if (ra !== rb) return ra - rb
  if (a.ts_confirm !== b.ts_confirm) return b.ts_confirm - a.ts_confirm
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0
}

export function sortFeed(feed: FeedEvents): EventView[] {
  return Object.values(feed).sort(compareEvents)
}

function prune(feed: FeedEvents): FeedEvents {
  const ids = Object.keys(feed)
  if (ids.length <= FEED_LIMIT) return feed
  const keep = ids
    .sort((a, b) => feed[b].ts_confirm - feed[a].ts_confirm)
    .slice(0, FEED_LIMIT)
  return Object.fromEntries(keep.map((id) => [id, feed[id]]))
}

export function parseMessage(raw: unknown): WsMessage | null {
  if (typeof raw !== 'string') return null
  let data: unknown
  try {
    data = JSON.parse(raw)
  } catch {
    return null
  }
  if (typeof data !== 'object' || data === null) return null
  const { kind, event } = data as { kind?: unknown; event?: unknown }
  if (kind !== 'event_new' && kind !== 'event_update') return null
  if (!isEventView(event)) return null
  return { kind, event }
}

function isEventView(x: unknown): x is EventView {
  if (typeof x !== 'object' || x === null) return false
  const e = x as Partial<EventView>
  return (
    typeof e.id === 'string' &&
    typeof e.camera_id === 'string' &&
    typeof e.type === 'string' &&
    typeof e.severity === 'string' &&
    typeof e.status === 'string' &&
    typeof e.ts_confirm === 'number'
  )
}
