import type { Camera, RuleSpec, Zone } from '../api/types.ts'

// Ограничения полигона по PLAN.md (BE-8): от 3 до 50 точек, координаты в долях кадра 0..1
export const MIN_POINTS = 3
export const MAX_POINTS = 50
const HISTORY_LIMIT = 100
const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/

export type Point = [number, number]

export interface RuleDraft {
  key: string
  type: string
  enabled: boolean
  zone: string | null
  schedule: [string, string] | null
  // Значения полей ввода; пустая строка — параметр не передаётся, сервер берёт default
  params: Record<string, string>
}

export interface Draft {
  zones: Zone[]
  rules: RuleDraft[]
}

let ruleSeq = 0
const ruleKey = () => `rule-${++ruleSeq}`

export function draftFromCamera(camera: Camera): Draft {
  return {
    zones: camera.zones.map((z) => ({ id: z.id, name: z.name, polygon: z.polygon.map(([x, y]) => [x, y] as Point) })),
    rules: camera.rules.map((r) => ({
      key: ruleKey(),
      type: r.type,
      enabled: r.enabled,
      zone: r.zone,
      schedule: r.schedule ? [r.schedule[0], r.schedule[1]] : null,
      params: Object.fromEntries(Object.entries(r.params ?? {}).map(([k, v]) => [k, String(v)])),
    })),
  }
}

export function newRule(spec: RuleSpec): RuleDraft {
  return { key: ruleKey(), type: spec.type, enabled: true, zone: null, schedule: null, params: {} }
}

// Тело PUT /api/cameras/{id}: поля камеры без изменений, зоны и правила из черновика
export function cameraFromDraft(camera: Camera, draft: Draft): Camera {
  return {
    id: camera.id,
    name: camera.name,
    source: camera.source,
    fps: camera.fps,
    zones: draft.zones.map((z) => ({ id: z.id, name: z.name, polygon: z.polygon.map(([x, y]) => [x, y]) })),
    rules: draft.rules.map((r) => ({
      type: r.type,
      enabled: r.enabled,
      zone: r.zone,
      schedule: r.schedule,
      params: Object.fromEntries(
        Object.entries(r.params)
          .filter(([, v]) => v.trim() !== '')
          .map(([k, v]) => [k, Number(v.replace(',', '.'))]),
      ),
    })),
  }
}

// Позиция курсора → доли кадра 0..1 относительно показанного изображения, при любом масштабе
export function normalizePoint(
  clientX: number,
  clientY: number,
  rect: { left: number; top: number; width: number; height: number },
): Point {
  const clamp = (v: number) => Math.min(1, Math.max(0, v))
  const round = (v: number) => Math.round(v * 10000) / 10000
  return [round(clamp((clientX - rect.left) / rect.width)), round(clamp((clientY - rect.top) / rect.height))]
}

export function newZoneId(zones: Zone[]): string {
  const ids = new Set(zones.map((z) => z.id))
  let n = zones.length + 1
  while (ids.has(`zone_${n}`)) n++
  return `zone_${n}`
}

export function updateZone(draft: Draft, zoneId: string, update: (z: Zone) => Zone): Draft {
  return { ...draft, zones: draft.zones.map((z) => (z.id === zoneId ? update(z) : z)) }
}

export function addPoint(draft: Draft, zoneId: string, p: Point): Draft {
  return updateZone(draft, zoneId, (z) => (z.polygon.length >= MAX_POINTS ? z : { ...z, polygon: [...z.polygon, p] }))
}

export function movePoint(draft: Draft, zoneId: string, index: number, p: Point): Draft {
  return updateZone(draft, zoneId, (z) => ({ ...z, polygon: z.polygon.map((q, i) => (i === index ? p : q)) }))
}

export function removePoint(draft: Draft, zoneId: string, index: number): Draft {
  return updateZone(draft, zoneId, (z) => ({ ...z, polygon: z.polygon.filter((_, i) => i !== index) }))
}

export function rulesUsingZone(draft: Draft, zoneId: string): RuleDraft[] {
  return draft.rules.filter((r) => r.zone === zoneId)
}

// Проверка перед PUT; окончательно камеру проверяет сервер (422 с detail)
export function validateDraft(draft: Draft, specs: RuleSpec[]): string[] {
  const errors: string[] = []
  const ids = new Set<string>()
  draft.zones.forEach((z, i) => {
    const label = z.name.trim() || `зона ${i + 1}`
    if (ids.has(z.id)) errors.push(`Зона «${label}»: id ${z.id} повторяется`)
    ids.add(z.id)
    if (!z.name.trim()) errors.push(`Зона ${i + 1}: укажите название`)
    const n = z.polygon.length
    if (n < MIN_POINTS || n > MAX_POINTS) {
      errors.push(`Зона «${label}»: нужно от ${MIN_POINTS} до ${MAX_POINTS} точек, сейчас ${n}`)
    }
  })
  draft.rules.forEach((r) => {
    const spec = specs.find((s) => s.type === r.type)
    const label = spec?.title ?? r.type
    if (!spec) {
      errors.push(`Правило ${r.type}: нет в /api/rules, удалите его`)
      return
    }
    if (spec.needs_zone && !r.zone) errors.push(`«${label}»: выберите зону`)
    if (r.zone && !ids.has(r.zone)) errors.push(`«${label}»: зоны ${r.zone} нет у камеры`)
    if (r.schedule && !r.schedule.every((t) => TIME_RE.test(t))) {
      errors.push(`«${label}»: расписание в формате ЧЧ:ММ`)
    }
    for (const [name, value] of Object.entries(r.params)) {
      if (value.trim() === '') continue
      const num = Number(value.replace(',', '.'))
      if (!Number.isFinite(num) || num < 0) errors.push(`«${label}»: ${name} должен быть числом не меньше 0`)
    }
  })
  return errors
}

const comparable = (d: Draft) =>
  JSON.stringify({ zones: d.zones, rules: d.rules.map(({ key: _key, ...r }) => r) })

export function sameDraft(a: Draft, b: Draft): boolean {
  return comparable(a) === comparable(b)
}

// История для «Отменить»: правки с одинаковым ключом (перетаскивание, ввод в одно поле) — один шаг
export interface History {
  present: Draft
  past: Draft[]
  lastKey: string | null
}

export type HistoryAction =
  | { type: 'reset'; draft: Draft }
  | { type: 'edit'; update: (d: Draft) => Draft; key?: string }
  | { type: 'undo' }

export function historyReducer(state: History, action: HistoryAction): History {
  switch (action.type) {
    case 'reset':
      return { present: action.draft, past: [], lastKey: null }
    case 'undo': {
      if (state.past.length === 0) return state
      return { present: state.past[state.past.length - 1], past: state.past.slice(0, -1), lastKey: null }
    }
    case 'edit': {
      const next = action.update(state.present)
      if (next === state.present) return state
      const key = action.key ?? null
      const coalesce = key !== null && key === state.lastKey
      const past = coalesce ? state.past : [...state.past, state.present].slice(-HISTORY_LIMIT)
      return { present: next, past, lastKey: key }
    }
  }
}
