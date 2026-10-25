import { useState } from 'react'
import type { Catalog } from '../api/useCatalog.ts'
import { STATUS_LABEL } from '../alerts/feed.ts'
import { formatTs, fromLocalInput, toLocalInput } from '../alerts/format.ts'
import { STATUSES, hasFilters, type JournalFilters as Filters } from './query.ts'

interface Props {
  filters: Filters
  catalog: Catalog
  onChange: (patch: Partial<Filters>) => void
  onReset: () => void
}

const PRESETS = [
  { label: 'Час', sec: 3600 },
  { label: 'Сутки', sec: 24 * 3600 },
  { label: '7 дней', sec: 7 * 24 * 3600 },
]

// Кнопка периода подсвечена, пока начало периода отличается от выбранного не больше чем на 10 минут
function presetOf(f: Filters) {
  return PRESETS.find((p) => f.to === undefined && f.from !== undefined && Math.abs(Date.now() / 1000 - p.sec - f.from) < 600)
}

// Период с датами из раскрытой панели, а не одной из кнопок периода
function customDates(f: Filters): boolean {
  return (f.from !== undefined || f.to !== undefined) && !presetOf(f)
}

// Число фильтров в раскрывающейся панели; период из кнопок виден и так
export function activeCount(f: Filters): number {
  return [f.type, f.camera_id, f.zone_id, f.status].filter(Boolean).length + (customDates(f) ? 1 : 0)
}

// Всегда видны период и кнопка «Фильтры»; остальные поля раскрываются по нажатию.
// Значения хранятся в адресе страницы, поэтому сворачивание панели их не сбрасывает
export function JournalFilters({ filters, catalog, onChange, onReset }: Props) {
  const [open, setOpen] = useState(false)
  const count = activeCount(filters)
  const preset = presetOf(filters)

  const camera = catalog.cameras.find((c) => c.id === filters.camera_id)
  const zones = filters.camera_id
    ? (camera?.zones ?? []).map((z) => ({ key: z.id, id: z.id, label: z.name }))
    : catalog.cameras.flatMap((c) => c.zones.map((z) => ({ key: `${c.id}/${z.id}`, id: z.id, label: `${z.name} (${c.name})` })))
  const noZones = !catalog.loading && zones.length === 0

  const types = [...catalog.types]
  if (filters.type && !types.some((t) => t.type === filters.type)) {
    types.push({ type: filters.type, title: filters.type, inRules: false })
  }
  const cameras = catalog.cameras.map((c) => ({ id: c.id, name: c.name }))
  if (filters.camera_id && !camera) cameras.push({ id: filters.camera_id, name: filters.camera_id })
  if (filters.zone_id && !zones.some((z) => z.id === filters.zone_id)) {
    zones.push({ key: filters.zone_id, id: filters.zone_id, label: filters.zone_id })
  }

  const changeCamera = (cameraId: string) => {
    const next = catalog.cameras.find((c) => c.id === cameraId)
    const keepZone = !cameraId || next?.zones.some((z) => z.id === filters.zone_id)
    onChange({ camera_id: cameraId || undefined, zone_id: keepZone ? filters.zone_id : undefined })
  }

  // Выбранные фильтры свёрнутой панели: метки, каждую можно снять
  const active: { key: string; label: string; clear: Partial<Filters> }[] = []
  if (filters.type) {
    active.push({ key: 'type', label: `Нарушение: ${types.find((t) => t.type === filters.type)?.title ?? filters.type}`, clear: { type: undefined } })
  }
  if (filters.status) {
    active.push({ key: 'status', label: `Решение: ${STATUS_LABEL[filters.status as keyof typeof STATUS_LABEL] ?? filters.status}`, clear: { status: undefined } })
  }
  if (filters.camera_id) {
    active.push({ key: 'camera', label: `Камера: ${cameras.find((c) => c.id === filters.camera_id)?.name ?? filters.camera_id}`, clear: { camera_id: undefined, zone_id: undefined } })
  }
  if (filters.zone_id) {
    active.push({ key: 'zone', label: `Зона: ${zones.find((z) => z.id === filters.zone_id)?.label ?? filters.zone_id}`, clear: { zone_id: undefined } })
  }
  if (customDates(filters)) {
    const from = filters.from !== undefined ? `с ${formatTs(filters.from)}` : ''
    const to = filters.to !== undefined ? `по ${formatTs(filters.to)}` : ''
    active.push({ key: 'dates', label: `Даты: ${[from, to].filter(Boolean).join(' ')}`, clear: { from: undefined, to: undefined } })
  }

  return (
    <div className="filters-wrap">
      <div className="filters-bar">
        <div className="segmented period" role="group" aria-label="Период">
          {PRESETS.map((p) => (
            <button
              key={p.label}
              type="button"
              aria-pressed={preset === p}
              onClick={() => onChange({ from: Math.floor(Date.now() / 1000) - p.sec, to: undefined })}
            >
              {p.label}
            </button>
          ))}
          <button
            type="button"
            aria-pressed={filters.from === undefined && filters.to === undefined}
            onClick={() => onChange({ from: undefined, to: undefined })}
          >
            Всё время
          </button>
        </div>
        <button
          type="button"
          className={count > 0 ? 'btn filters-btn filters-btn-active' : 'btn filters-btn'}
          aria-expanded={open}
          aria-controls="journal-filters"
          onClick={() => setOpen((o) => !o)}
        >
          Фильтры
          {count > 0 && (
            <span className="count-badge" aria-label={`выбрано: ${count}`}>
              {count}
            </span>
          )}
        </button>
        {hasFilters(filters) && (
          <button type="button" className="btn btn-ghost" onClick={onReset}>
            Сбросить
          </button>
        )}
      </div>

      {!open && active.length > 0 && (
        <ul className="filter-chips" aria-label="Выбранные фильтры">
          {active.map((a) => (
            <li key={a.key}>
              <button type="button" className="filter-chip" onClick={() => onChange(a.clear)} aria-label={`Убрать фильтр: ${a.label}`}>
                {a.label}
                <span aria-hidden="true">×</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {catalog.error && (
        <p className="form-error" role="alert">
          Списки камер и нарушений не загружены: {catalog.error}.{' '}
          <button type="button" className="link-btn" onClick={catalog.reload}>
            Повторить
          </button>
        </p>
      )}

      {open && (
        <form id="journal-filters" className="filters" onSubmit={(e) => e.preventDefault()} aria-label="Фильтры журнала">
          <label className="field">
            <span className="field-label">Нарушение</span>
            <select value={filters.type ?? ''} onChange={(e) => onChange({ type: e.target.value || undefined })}>
              <option value="">Все нарушения</option>
              {types.map((t) => (
                <option key={t.type} value={t.type}>
                  {t.title}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span className="field-label">Решение</span>
            <select value={filters.status ?? ''} onChange={(e) => onChange({ status: e.target.value || undefined })}>
              <option value="">Любое</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABEL[s]}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span className="field-label">Камера</span>
            <select value={filters.camera_id ?? ''} onChange={(e) => changeCamera(e.target.value)}>
              <option value="">Все камеры</option>
              {cameras.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span className="field-label">Зона</span>
            <select
              value={filters.zone_id ?? ''}
              disabled={noZones && !filters.zone_id}
              onChange={(e) => onChange({ zone_id: e.target.value || undefined })}
            >
              <option value="">{noZones ? (filters.camera_id ? 'У камеры нет зон' : 'Зон нет') : 'Все зоны'}</option>
              {zones.map((z) => (
                <option key={z.key} value={z.id}>
                  {z.label}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span className="field-label">С даты</span>
            <input
              type="datetime-local"
              value={filters.from !== undefined ? toLocalInput(filters.from) : ''}
              onChange={(e) => onChange({ from: fromLocalInput(e.target.value) })}
            />
          </label>

          <label className="field">
            <span className="field-label">По дату</span>
            <input
              type="datetime-local"
              value={filters.to !== undefined ? toLocalInput(filters.to) : ''}
              onChange={(e) => {
                // Поле с точностью до минуты: конец периода включает всю минуту
                const ts = fromLocalInput(e.target.value)
                onChange({ to: ts === undefined ? undefined : ts + 59 })
              }}
            />
          </label>

          <div className="filters-actions">
            <button type="button" className="btn btn-primary" onClick={() => setOpen(false)}>
              Готово
            </button>
            {hasFilters(filters) && (
              <button type="button" className="btn btn-ghost" onClick={onReset}>
                Сбросить все фильтры
              </button>
            )}
          </div>

        </form>
      )}
    </div>
  )
}
