// Типы API по CONTRACT.md, раздел 6

export type Severity = 'critical' | 'high' | 'medium'
export type EventStatus = 'new' | 'confirmed' | 'false' | 'forwarded'
export type BBox = [number, number, number, number]

export interface EventView {
  id: string
  camera_id: string
  camera_name: string | null
  type: string
  title: string | null
  severity: Severity
  track_id: number
  bbox: BBox
  conf: number
  ts_start: number
  ts_confirm: number
  ts_end: number | null
  zone_id: string | null
  zone_name: string | null
  extra: Record<string, unknown>
  status: EventStatus
  comment: string | null
  snapshot_url: string | null
  clip_url: string | null
}

export interface EventsPage {
  items: EventView[]
  total: number
}

export interface WsMessage {
  kind: 'event_new' | 'event_update'
  event: EventView
}

export interface Status {
  detector: string
  backend: string
  cameras: { id: string; online: boolean; fps: number; latency_ms: number }[]
}
