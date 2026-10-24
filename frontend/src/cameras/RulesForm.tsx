import { useState } from 'react'
import type { RuleSpec, Zone } from '../api/types.ts'
import { SEVERITY_LABEL } from '../alerts/feed.ts'
import type { RuleDraft } from './editorModel.ts'

interface Props {
  rules: RuleDraft[]
  specs: RuleSpec[]
  zones: Zone[]
  onAdd: (spec: RuleSpec) => void
  onRemove: (key: string) => void
  // field: ключ поля для объединения ввода в один шаг отмены
  onChange: (key: string, update: (r: RuleDraft) => RuleDraft, field: string) => void
}

const DEFAULT_SCHEDULE: [string, string] = ['08:00', '20:00']

// Правила камеры. Типы, названия, необходимость зоны и параметры берутся из GET /api/rules
export function RulesForm({ rules, specs, zones, onAdd, onRemove, onChange }: Props) {
  const [addType, setAddType] = useState('')

  return (
    <div className="rules-form">
      {rules.length === 0 && <p className="muted">У камеры нет правил</p>}
      {rules.map((r, idx) => {
        const spec = specs.find((s) => s.type === r.type)
        const set = (update: (r: RuleDraft) => RuleDraft, field: string) => onChange(r.key, update, field)
        return (
          <fieldset key={r.key} className="rule-card" data-rule-type={r.type}>
            <legend className="sr-only">Правило {idx + 1}</legend>
            <div className="rule-head">
              <label className="rule-enabled">
                <input
                  type="checkbox"
                  checked={r.enabled}
                  onChange={(e) => set((x) => ({ ...x, enabled: e.target.checked }), 'enabled')}
                />
                <span className="rule-title">{spec?.title ?? r.type}</span>
              </label>
              <code className="muted">{r.type}</code>
              {spec && <span className={`badge badge-${spec.severity}`}>{SEVERITY_LABEL[spec.severity] ?? spec.severity}</span>}
              <button type="button" className="link-btn rule-remove" onClick={() => onRemove(r.key)}>
                Удалить правило
              </button>
            </div>

            {!spec ? (
              <p className="form-error">Правила {r.type} нет в /api/rules: сервер не примет камеру, пока оно есть</p>
            ) : (
              <div className="rule-fields">
                <label>
                  <span>Зона{spec.needs_zone ? ' (обязательно)' : ''}</span>
                  <select
                    value={r.zone ?? ''}
                    onChange={(e) => set((x) => ({ ...x, zone: e.target.value || null }), 'zone')}
                  >
                    <option value="">{spec.needs_zone ? 'Выберите зону' : 'Весь кадр'}</option>
                    {zones.map((z) => (
                      <option key={z.id} value={z.id}>
                        {z.name || z.id}
                      </option>
                    ))}
                    {r.zone && !zones.some((z) => z.id === r.zone) && <option value={r.zone}>{r.zone} (нет у камеры)</option>}
                  </select>
                </label>

                <div className="rule-schedule">
                  <label className="inline-check">
                    <input
                      type="checkbox"
                      checked={r.schedule !== null}
                      onChange={(e) => set((x) => ({ ...x, schedule: e.target.checked ? DEFAULT_SCHEDULE : null }), 'schedule')}
                    />
                    <span>По расписанию</span>
                  </label>
                  {r.schedule ? (
                    <span className="schedule-times">
                      <input
                        type="time"
                        aria-label="Начало"
                        value={r.schedule[0]}
                        onChange={(e) => set((x) => ({ ...x, schedule: [e.target.value, x.schedule?.[1] ?? ''] }), 'schedule-from')}
                      />
                      <span>–</span>
                      <input
                        type="time"
                        aria-label="Конец"
                        value={r.schedule[1]}
                        onChange={(e) => set((x) => ({ ...x, schedule: [x.schedule?.[0] ?? '', e.target.value] }), 'schedule-to')}
                      />
                    </span>
                  ) : (
                    <span className="muted">круглосуточно</span>
                  )}
                </div>

                {spec.params.map((p) => (
                  <label key={p.name} className="rule-param">
                    <span>
                      <code>{p.name}</code>
                      {p.unit && <span className="muted">, {p.unit}</span>}
                    </span>
                    <input
                      type="number"
                      inputMode="decimal"
                      step="any"
                      min={0}
                      placeholder={`по умолчанию ${String(p.default)}`}
                      value={r.params[p.name] ?? ''}
                      onChange={(e) => set((x) => ({ ...x, params: { ...x.params, [p.name]: e.target.value } }), `param-${p.name}`)}
                    />
                  </label>
                ))}
              </div>
            )}
          </fieldset>
        )
      })}

      <div className="rule-add">
        <select value={addType} onChange={(e) => setAddType(e.target.value)} aria-label="Тип нового правила">
          <option value="">Добавить правило…</option>
          {specs.map((s) => (
            <option key={s.type} value={s.type}>
              {s.title}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn btn-small"
          disabled={!addType}
          onClick={() => {
            const spec = specs.find((s) => s.type === addType)
            if (spec) onAdd(spec)
            setAddType('')
          }}
        >
          Добавить
        </button>
      </div>
    </div>
  )
}
