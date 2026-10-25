import { useEffect, useRef, useState } from 'react'
import type { RuleSpec, Zone } from '../api/types.ts'
import { SEVERITY_LABEL } from '../alerts/feed.ts'
import { ConfirmAction } from '../components/ConfirmAction.tsx'
import type { RuleDraft } from './editorModel.ts'
import { BASIC_PARAMS, paramLabel } from './ruleText.ts'

interface Props {
  rules: RuleDraft[]
  specs: RuleSpec[]
  zones: Zone[]
  // режим просмотра: поля показаны, но не меняются
  disabled: boolean
  onAdd: (spec: RuleSpec) => void
  onRemove: (key: string) => void
  // field: ключ поля для объединения ввода в один шаг отмены
  onChange: (key: string, update: (r: RuleDraft) => RuleDraft, field: string) => void
}

const DEFAULT_SCHEDULE: [string, string] = ['08:00', '20:00']

type Param = RuleSpec['params'][number]

// Сводка правила одной строкой: где, когда и основные параметры
function summary(r: RuleDraft, spec: RuleSpec, zones: Zone[]): { text: string; problem: string | null } {
  const zone = r.zone ? (zones.find((z) => z.id === r.zone)?.name ?? r.zone) : null
  const parts = [
    zone ? `зона «${zone}»` : 'весь кадр',
    r.schedule ? `с ${r.schedule[0]} до ${r.schedule[1]}` : 'круглосуточно',
    ...spec.params
      .filter((p) => BASIC_PARAMS.has(p.name) && (r.params[p.name] ?? '').trim() !== '')
      .map((p) => `${paramLabel(p.name).toLowerCase()} ${r.params[p.name]}${p.unit ? ` ${p.unit}` : ''}`),
  ]
  let problem: string | null = null
  if (spec.needs_zone && !r.zone) problem = 'Выберите зону'
  else if (r.zone && !zones.some((z) => z.id === r.zone)) problem = 'Зона удалена, выберите другую'
  return { text: parts.join(' · '), problem }
}

// Правила камеры. Типы, названия, необходимость зоны и параметры берутся из GET /api/rules
export function RulesForm({ rules, specs, zones, disabled, onAdd, onRemove, onChange }: Props) {
  const [addType, setAddType] = useState('')
  const [open, setOpen] = useState<Set<string>>(() => new Set())
  // Только что добавленное правило раскрывается сразу. После сохранения черновик пересоздаётся
  // с новыми ключами при том же числе правил: такие правила не раскрываются
  const known = useRef(new Set(rules.map((r) => r.key)))
  useEffect(() => {
    const grew = rules.length > known.current.size
    const added = rules.filter((r) => !known.current.has(r.key)).map((r) => r.key)
    known.current = new Set(rules.map((r) => r.key))
    if (grew && added.length > 0) setOpen((o) => new Set([...o, ...added]))
  }, [rules])

  const toggle = (key: string) =>
    setOpen((o) => {
      const next = new Set(o)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  return (
    <div className="rules-form" data-readonly={disabled || undefined}>
      {rules.length === 0 && <p className="muted">Правил нет: камера ничего не проверяет.</p>}
      {rules.map((r, idx) => {
        const spec = specs.find((s) => s.type === r.type)
        const set = (update: (r: RuleDraft) => RuleDraft, field: string) => onChange(r.key, update, field)
        const expanded = open.has(r.key)
        const info = spec ? summary(r, spec, zones) : null
        const basic = spec?.params.filter((p) => BASIC_PARAMS.has(p.name)) ?? []
        const advanced = spec?.params.filter((p) => !BASIC_PARAMS.has(p.name)) ?? []
        const param = (p: Param) => (
          <label key={p.name} className="field rule-param">
            <span className="field-label">
              {paramLabel(p.name)}
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
        )
        return (
          <section key={r.key} className={r.enabled ? 'rule-card' : 'rule-card rule-off'} data-rule-type={r.type} aria-label={`Правило ${idx + 1}`}>
            <div className="rule-head">
              <label className="switch" title={r.enabled ? 'Выключить правило' : 'Включить правило'}>
                <input
                  type="checkbox"
                  role="switch"
                  checked={r.enabled}
                  disabled={disabled}
                  onChange={(e) => set((x) => ({ ...x, enabled: e.target.checked }), 'enabled')}
                />
                <span className="sr-only">{r.enabled ? 'Правило включено' : 'Правило выключено'}</span>
              </label>
              <div className="rule-main">
                <p className="rule-title">
                  {spec?.title ?? r.type}
                  {spec && <span className={`badge badge-${spec.severity}`}>{SEVERITY_LABEL[spec.severity] ?? spec.severity}</span>}
                </p>
                {info ? (
                  <p className="rule-summary">
                    {!r.enabled && <span>выключено · </span>}
                    {info.text}
                    {info.problem && <span className="form-error"> · {info.problem}</span>}
                  </p>
                ) : (
                  <p className="rule-summary form-error">Правила «{r.type}» нет на сервере: удалите его, иначе настройки не сохранятся</p>
                )}
              </div>
              {spec && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm rule-toggle"
                  aria-expanded={expanded}
                  onClick={() => toggle(r.key)}
                >
                  {expanded ? 'Свернуть' : disabled ? 'Подробнее' : 'Настроить'}
                </button>
              )}
            </div>

            {(expanded || !spec) && (
              // В режиме просмотра поля видны, но недоступны; кнопка «Подробнее» в шапке работает
              <fieldset className="rule-body" disabled={disabled}>
                <legend className="sr-only">Настройки правила</legend>
                {spec && (
                  <div className="rule-fields">
                    <label className="field">
                      <span className="field-label">Где следить</span>
                      <select value={r.zone ?? ''} onChange={(e) => set((x) => ({ ...x, zone: e.target.value || null }), 'zone')}>
                        <option value="">{spec.needs_zone ? 'Выберите зону' : 'Весь кадр'}</option>
                        {zones.map((z) => (
                          <option key={z.id} value={z.id}>
                            {z.name || z.id}
                          </option>
                        ))}
                        {r.zone && !zones.some((z) => z.id === r.zone) && <option value={r.zone}>{r.zone} (нет у камеры)</option>}
                      </select>
                      {spec.needs_zone && <span className="field-help">Правило работает только внутри зоны.</span>}
                    </label>

                    <div className="field rule-schedule">
                      <span className="field-label">Когда следить</span>
                      <label className="inline-check">
                        <input
                          type="checkbox"
                          checked={r.schedule !== null}
                          onChange={(e) => set((x) => ({ ...x, schedule: e.target.checked ? DEFAULT_SCHEDULE : null }), 'schedule')}
                        />
                        <span>Только в рабочие часы</span>
                      </label>
                      {r.schedule ? (
                        <span className="schedule-times">
                          <span>с</span>
                          <input
                            type="time"
                            aria-label="Начало"
                            value={r.schedule[0]}
                            onChange={(e) => set((x) => ({ ...x, schedule: [e.target.value, x.schedule?.[1] ?? ''] }), 'schedule-from')}
                          />
                          <span>до</span>
                          <input
                            type="time"
                            aria-label="Конец"
                            value={r.schedule[1]}
                            onChange={(e) => set((x) => ({ ...x, schedule: [x.schedule?.[0] ?? '', e.target.value] }), 'schedule-to')}
                          />
                        </span>
                      ) : (
                        <span className="field-help">Сейчас круглосуточно.</span>
                      )}
                    </div>

                    {basic.map(param)}
                  </div>
                )}

                {advanced.length > 0 && (
                  <details className="more">
                    <summary>Дополнительные настройки</summary>
                    <p className="field-help">Для специалиста. Пустое поле: сервер берёт значение по умолчанию.</p>
                    <div className="rule-fields">{advanced.map(param)}</div>
                  </details>
                )}

                {!disabled && (
                  <div className="rule-danger">
                    <ConfirmAction
                      label="Удалить правило"
                      question={`Удалить правило «${spec?.title ?? r.type}»? Изменение вступит в силу после сохранения.`}
                      onConfirm={() => onRemove(r.key)}
                    />
                  </div>
                )}
              </fieldset>
            )}
          </section>
        )
      })}

      {!disabled && (
        <div className="rule-add">
          <select value={addType} onChange={(e) => setAddType(e.target.value)} aria-label="Тип нового правила">
            <option value="">Добавить правило…</option>
            {specs.map((s) => (
              <option key={s.type} value={s.type}>
                {s.title}
              </option>
            ))}
          </select>
          {addType && (
            <button
              type="button"
              className="btn"
              onClick={() => {
                const spec = specs.find((s) => s.type === addType)
                if (spec) onAdd(spec)
                setAddType('')
              }}
            >
              Добавить
            </button>
          )}
        </div>
      )}
    </div>
  )
}
