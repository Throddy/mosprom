import type { Catalog } from '../api/useCatalog.ts'
import { STATUS_LABEL } from '../alerts/feed.ts'
import { fromLocalInput, toLocalInput } from '../alerts/format.ts'
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

export function JournalFilters({ filters, catalog, onChange, onReset }: Props) {
  const camera = catalog.cameras.find((c) => c.id === filters.camera_id)
  const zones = filters.camera_id
    ? (camera?.zones ?? []).map((z) => ({ key: z.id, id: z.id, label: z.name }))
    : catalog.cameras.flatMap((c) => c.zones.map((z) => ({ key: `${c.id}/${z.id}`, id: z.id, label: `${z.name} · ${c.name}` })))
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

  return (
    <form className="filters" onSubmit={(e) => e.preventDefault()} aria-label="Фильтры журнала">
      <label>
        <span>Тип</span>
        <select value={filters.type ?? ''} onChange={(e) => onChange({ type: e.target.value || undefined })}>
          <option value="">Все типы</option>
          {types.map((t) => (
            <option key={t.type} value={t.type}>
              {t.inRules ? t.title : `${t.title} (нет в /api/rules)`}
            </option>
          ))}
        </select>
      </label>

      <label>
        <span>Камера</span>
        <select value={filters.camera_id ?? ''} onChange={(e) => changeCamera(e.target.value)}>
          <option value="">Все камеры</option>
          {cameras.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>

      <label>
        <span>Зона</span>
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

      <label>
        <span>Статус</span>
        <select value={filters.status ?? ''} onChange={(e) => onChange({ status: e.target.value || undefined })}>
          <option value="">Все статусы</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABEL[s]}
            </option>
          ))}
        </select>
      </label>

      <label>
        <span>С</span>
        <input
          type="datetime-local"
          value={filters.from !== undefined ? toLocalInput(filters.from) : ''}
          onChange={(e) => onChange({ from: fromLocalInput(e.target.value) })}
        />
      </label>

      <label>
        <span>По</span>
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
        <span className="muted">Период:</span>
        {PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            className="btn btn-small"
            onClick={() => onChange({ from: Math.floor(Date.now() / 1000) - p.sec, to: undefined })}
          >
            {p.label}
          </button>
        ))}
        <button
          type="button"
          className="btn btn-small"
          onClick={() => onChange({ from: undefined, to: undefined })}
          disabled={filters.from === undefined && filters.to === undefined}
        >
          Всё время
        </button>
        <button type="button" className="btn btn-small" onClick={onReset} disabled={!hasFilters(filters)}>
          Сбросить фильтры
        </button>
      </div>

      {catalog.error && (
        <p className="filters-error" role="alert">
          Справочники не загружены: {catalog.error}.{' '}
          <button type="button" className="link-btn" onClick={catalog.reload}>
            Повторить
          </button>
        </p>
      )}
    </form>
  )
}
