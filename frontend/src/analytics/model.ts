import type { Benchmark, RuleMetrics } from '../api/types.ts'

// Вид замера. В записи нет отдельного поля для способа доступа к TPU, он указан в device
export type BenchKind = 'onnx' | 'linq-service' | 'linq-accelerator' | 'linq' | 'other'

export function benchKind(b: Benchmark): BenchKind {
  if (b.backend === 'onnx') return 'onnx'
  if (b.backend !== 'linq') return 'other'
  if (/только время ускорителя/i.test(b.device)) return 'linq-accelerator'
  if (/ретранслятор|rabbitmq/i.test(b.device)) return 'linq-service'
  return 'linq'
}

export const KIND_LABEL: Record<BenchKind, string> = {
  onnx: 'ONNX Runtime',
  'linq-service': 'LinQ TPU через облачный стенд',
  'linq-accelerator': 'LinQ TPU, только время ускорителя',
  linq: 'LinQ TPU',
  other: 'другой бэкенд',
}

export function byKind(list: Benchmark[], kind: BenchKind): Benchmark[] {
  return list.filter((b) => benchKind(b) === kind).sort((a, b) => a.streams - b.streams)
}

export function best(list: Benchmark[]): Benchmark | null {
  return list.reduce<Benchmark | null>((acc, b) => (acc === null || b.fps > acc.fps ? b : acc), null)
}

// CONTRACT.md, раздел 8: камер на плату = floor(fps / fps_камеры), fps — наибольший среди backend = linq
export function contractLinqRecord(list: Benchmark[]): Benchmark | null {
  return best(list.filter((b) => b.backend === 'linq'))
}

export function camerasPerBoard(boardFps: number, cameraFps: number): number {
  if (!(cameraFps > 0) || !(boardFps >= 0)) return 0
  return Math.floor(boardFps / cameraFps)
}

export function boardsNeeded(cameras: number, perBoard: number): number | null {
  if (perBoard <= 0) return null
  return Math.ceil(cameras / perBoard)
}

// precision и recall из tp, fp, fn; null, если знаменатель 0 (нет тревог или нет разметки)
export function ruleRates(m: RuleMetrics): { precision: number | null; recall: number | null; labeled: number; alarms: number } {
  const alarms = m.tp + m.fp
  const labeled = m.tp + m.fn
  return {
    precision: alarms > 0 ? m.tp / alarms : null,
    recall: labeled > 0 ? m.tp / labeled : null,
    labeled,
    alarms,
  }
}

export interface Entry {
  key: string
  value: number
}

// Пары {key, value} по убыванию значения, при равенстве по ключу
export function entries(rec: Record<string, number> | undefined): Entry[] {
  return Object.entries(rec ?? {})
    .map(([key, value]) => ({ key, value: Number(value) || 0 }))
    .sort((a, b) => b.value - a.value || a.key.localeCompare(b.key))
}

export function share(part: number, whole: number): number | null {
  return whole > 0 ? part / whole : null
}

const numFmt = new Map<number, Intl.NumberFormat>()

export function fmt(n: number, digits = 0): string {
  let f = numFmt.get(digits)
  if (!f) {
    f = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits, minimumFractionDigits: 0 })
    numFmt.set(digits, f)
  }
  return f.format(n)
}

export function fmtPct(v: number | null, digits = 0): string {
  return v === null ? '—' : `${fmt(v * 100, digits)} %`
}

export type Period = 'all' | '7d' | '24h'

export const PERIODS: { id: Period; label: string; sec: number | null }[] = [
  { id: 'all', label: 'Всё время', sec: null },
  { id: '7d', label: '7 дней', sec: 7 * 24 * 3600 },
  { id: '24h', label: '24 часа', sec: 24 * 3600 },
]

export function periodRange(period: Period, nowSec: number): { from?: number } {
  const p = PERIODS.find((x) => x.id === period)
  return p?.sec ? { from: Math.floor(nowSec - p.sec) } : {}
}
