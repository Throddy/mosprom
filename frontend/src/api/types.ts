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

export interface Zone {
  id: string
  name: string
  polygon: [number, number][]
}

export interface RuleConfig {
  type: string
  enabled: boolean
  zone: string | null
  schedule: [string, string] | null
  params: Record<string, unknown>
}

export interface Camera {
  id: string
  name: string
  source: string
  fps: number
  zones: Zone[]
  rules: RuleConfig[]
}

// Описание правила из GET /api/rules, раздел 5
export interface RuleSpec {
  type: string
  title: string
  severity: Severity
  needs_zone: boolean
  params: { name: string; type: string; unit: string; default: unknown }[]
}

// Параметры GET /api/events; from и to в unix-секундах
export interface EventsQuery {
  type?: string
  camera_id?: string
  zone_id?: string
  status?: string
  severity?: string
  from?: number
  to?: number
  limit?: number
  offset?: number
}

// GET /api/stats, раздел 6; by_hour — 24 значения по часу ts_confirm по местному времени сервера
export interface Stats {
  total: number
  by_type: Record<string, number>
  by_camera: Record<string, number>
  by_severity: Record<string, number>
  by_status: Record<string, number>
  by_hour: number[]
  by_day: Record<string, number>
}

// Запись reports/benchmarks.json через GET /api/benchmarks, раздел 8; fps суммарно по потокам
export interface Benchmark {
  model: string
  backend: string
  device: string
  precision: string
  input: number
  streams: number
  fps: number
  latency_ms: { pre: number; infer: number; post: number; total: number }
  measured_at: string
}

export interface RuleMetrics {
  tp: number
  fp: number
  fn: number
  precision: number
  recall: number
}

// reports/metrics.json через GET /api/metrics, раздел 8; до ML-7 сервер отдаёт {}
export interface Metrics {
  test_set?: string
  rules?: Record<string, RuleMetrics>
}

export interface Status {
  detector: string
  backend: string
  cameras: { id: string; online: boolean; fps: number; latency_ms: number }[]
}
