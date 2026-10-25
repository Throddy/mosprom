import { useCallback, useEffect, useMemo, useReducer, useState } from 'react'
import { ApiError, putCamera, userMessage } from '../api/client.ts'
import { READ_ONLY_TITLE, noteForbidden, useReadOnly } from '../api/readOnly.ts'
import type { Camera, RuleSpec } from '../api/types.ts'
import {
  MAX_POINTS,
  MIN_POINTS,
  addPoint,
  cameraFromDraft,
  draftFromCamera,
  historyReducer,
  movePoint,
  newRule,
  newZoneId,
  removePoint,
  rulesUsingZone,
  sameDraft,
  updateZone,
  validateDraft,
  type Draft,
  type History,
} from './editorModel.ts'
import { ConfirmAction } from '../components/ConfirmAction.tsx'
import { RulesForm } from './RulesForm.tsx'
import { useFrame } from './useFrame.ts'
import { ZoneCanvas } from './ZoneCanvas.tsx'

interface Props {
  camera: Camera
  specs: RuleSpec[]
  // ошибка загрузки /api/rules: без описаний правил форму не проверить
  specsError: string | null
  onSaved: (camera: Camera) => void
}

type SaveState =
  | { state: 'idle' }
  | { state: 'saving' }
  | { state: 'saved'; at: number }
  | { state: 'error'; message: string; details: string[] }

const timeFmt = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

const initHistory = (camera: Camera): History => ({ present: draftFromCamera(camera), past: [], lastKey: null })

function isTyping(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName))
}

// Редактор зон и правил камеры: черновик меняется локально, на сервер уходит одним PUT /api/cameras/{id}
export function CameraEditor({ camera, specs, specsError, onSaved }: Props) {
  const [history, dispatch] = useReducer(historyReducer, camera, initHistory)
  const [base, setBase] = useState<Draft>(() => history.present)
  const draft = history.present
  const [selectedZone, setSelectedZone] = useState<string | null>(draft.zones[0]?.id ?? null)
  const [selectedPoint, setSelectedPoint] = useState<number | null>(null)
  const [blank, setBlank] = useState(false)
  const [save, setSave] = useState<SaveState>({ state: 'idle' })
  const [notice, setNotice] = useState<string | null>(null)
  const { frame, reload } = useFrame(camera.id)
  // Режим просмотра: сервер отказал в изменениях (403), редактирование скрыто
  const editable = useReadOnly() === null

  const dirty = !sameDraft(draft, base)
  const errors = useMemo(() => validateDraft(draft, specs), [draft, specs])
  const zone = draft.zones.find((z) => z.id === selectedZone) ?? null

  const edit = useCallback((update: (d: Draft) => Draft, key?: string) => {
    setNotice(null)
    setSave((s) => (s.state === 'error' ? { state: 'idle' } : s))
    dispatch({ type: 'edit', update, key })
  }, [])

  // Выбор не должен указывать на удалённую зону или точку, в том числе после «Отменить»
  useEffect(() => {
    if (selectedZone && !draft.zones.some((z) => z.id === selectedZone)) {
      setSelectedZone(draft.zones[0]?.id ?? null)
      setSelectedPoint(null)
    } else if (zone && selectedPoint !== null && selectedPoint >= zone.polygon.length) {
      setSelectedPoint(null)
    }
  }, [draft, selectedZone, selectedPoint, zone])

  const undo = useCallback(() => {
    setNotice(null)
    dispatch({ type: 'undo' })
  }, [])

  const deletePoint = useCallback(() => {
    if (!zone || selectedPoint === null) return
    edit((d) => removePoint(d, zone.id, selectedPoint))
    setSelectedPoint(null)
  }, [edit, zone, selectedPoint])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!editable || isTyping(e.target)) return
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        undo()
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selectedPoint !== null) {
          e.preventDefault()
          deletePoint()
        }
      } else if (e.key === 'Escape') {
        setSelectedPoint(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [undo, deletePoint, selectedPoint, editable])

  // Несохранённый черновик: подтверждение при уходе со страницы и переходах по разделам сайта.
  // В режиме просмотра сохранить черновик нельзя, поэтому уход не задерживается
  useEffect(() => {
    if (!dirty || !editable) return
    const onBeforeUnload = (e: BeforeUnloadEvent) => e.preventDefault()
    const onLinkClick = (e: MouseEvent) => {
      const link = e.target instanceof Element ? e.target.closest('a[href^="#/"]') : null
      if (link && !window.confirm('Изменения зон и правил не сохранены. Уйти без сохранения?')) {
        e.preventDefault()
        e.stopPropagation()
      }
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    document.addEventListener('click', onLinkClick, true)
    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload)
      document.removeEventListener('click', onLinkClick, true)
    }
  }, [dirty, editable])

  const addZone = () => {
    const id = newZoneId(draft.zones)
    edit((d) => ({ ...d, zones: [...d.zones, { id, name: `Зона ${d.zones.length + 1}`, polygon: [] }] }))
    setSelectedZone(id)
    setSelectedPoint(null)
  }

  const removeZone = () => {
    if (!zone) return
    const used = rulesUsingZone(draft, zone.id)
    if (used.length > 0) {
      const titles = used.map((r) => specs.find((s) => s.type === r.type)?.title ?? r.type)
      setNotice(`Зону «${zone.name}» используют правила: ${titles.join(', ')}. Сначала смените или удалите их зону.`)
      return
    }
    edit((d) => ({ ...d, zones: d.zones.filter((z) => z.id !== zone.id) }))
  }

  const resetDraft = () => {
    dispatch({ type: 'reset', draft: base })
    setSave({ state: 'idle' })
    setNotice(null)
  }

  const submit = () => {
    setSave({ state: 'saving' })
    putCamera(cameraFromDraft(camera, draft))
      .then((saved) => {
        const next = draftFromCamera(saved)
        setBase(next)
        dispatch({ type: 'reset', draft: next })
        setSave({ state: 'saved', at: Date.now() })
        onSaved(saved)
      })
      .catch((err: unknown) => {
        // Черновик не сбрасывается и не считается сохранённым: на сервере остались прежние зоны
        noteForbidden(err)
        if (err instanceof ApiError && err.status === 422 && err.detail) {
          setSave({ state: 'error', message: 'сервер не принял настройки', details: err.detail.split('; ') })
        } else {
          setSave({ state: 'error', message: userMessage(err), details: [] })
        }
      })
  }

  const canSave = editable && dirty && errors.length === 0 && save.state !== 'saving' && !specsError
  const showCanvas = frame.state === 'ready' || blank
  const points = zone?.polygon.length ?? 0

  return (
    <div className="editor" data-camera-id={camera.id}>
      {!editable && <p className="readonly-note">{READ_ONLY_TITLE}. Зоны и правила показаны без возможности изменения.</p>}

      <section className="step" aria-labelledby={`step1-${camera.id}`}>
        <div className="step-head">
          <span className="step-num" aria-hidden="true">
            1
          </span>
          <h4 id={`step1-${camera.id}`}>Опасная зона</h4>
        </div>

        {draft.zones.length === 0 ? (
          <div className="step-empty">
            <p className="muted">Зона — участок кадра, где действуют правила, например проезд погрузчика. У этой камеры зон пока нет.</p>
            {editable && (
              <button type="button" className={dirty ? 'btn' : 'btn btn-primary btn-lg'} onClick={addZone}>
                Новая зона
              </button>
            )}
          </div>
        ) : (
          <>
            <div className="zone-tabs" role="radiogroup" aria-label="Зоны камеры">
              {draft.zones.map((z) => {
                const ready = z.polygon.length >= MIN_POINTS
                return (
                  <button
                    key={z.id}
                    type="button"
                    role="radio"
                    aria-checked={z.id === selectedZone}
                    className="zone-tab"
                    data-zone-id={z.id}
                    title={z.id}
                    onClick={() => {
                      setSelectedZone(z.id)
                      setSelectedPoint(null)
                    }}
                  >
                    <span className="zone-tab-name">{z.name.trim() || 'Без названия'}</span>
                    <span className={ready ? 'zone-tab-meta' : 'zone-tab-meta zone-tab-warn'}>
                      {ready ? `точек: ${z.polygon.length}` : 'контур не готов'}
                    </span>
                  </button>
                )
              })}
              {editable && (
                <button type="button" className="btn btn-ghost zone-add" onClick={addZone}>
                  + Новая зона
                </button>
              )}
            </div>

            {zone && (
              <div className="zone-settings">
                <label className="field zone-name-field">
                  <span className="field-label">Название зоны</span>
                  <input
                    className="zone-name"
                    value={zone.name}
                    maxLength={100}
                    readOnly={!editable}
                    onChange={(e) => {
                      const name = e.target.value
                      edit((d) => updateZone(d, zone.id, (x) => ({ ...x, name })), `name-${zone.id}`)
                    }}
                  />
                </label>
                {editable && (
                  <ConfirmAction
                    label="Удалить зону"
                    question={`Удалить зону «${zone.name.trim() || 'Без названия'}» вместе с контуром? Изменение вступит в силу после сохранения.`}
                    onConfirm={removeZone}
                  />
                )}
              </div>
            )}
          </>
        )}
        {notice && (
          <p className="form-error" role="alert">
            {notice}
          </p>
        )}
      </section>

      <section className="step" aria-labelledby={`step2-${camera.id}`}>
        <div className="step-head">
          <span className="step-num" aria-hidden="true">
            2
          </span>
          <h4 id={`step2-${camera.id}`}>Контур на кадре</h4>
          {editable && (
            <div className="step-tools" role="toolbar" aria-label="Разметка контура">
              {selectedPoint !== null && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={deletePoint} title="Delete">
                  Удалить точку
                </button>
              )}
              {history.past.length > 0 && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={undo} title="Ctrl+Z">
                  Отменить
                </button>
              )}
              {frame.state === 'ready' && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={reload}>
                  Обновить кадр
                </button>
              )}
            </div>
          )}
        </div>

        {editable && (
          <p className="step-hint" role="status">
            {contourHint(zone ? zone.name.trim() || 'Без названия' : null, points, draft.zones.length > 0, selectedPoint)}
          </p>
        )}

        {showCanvas ? (
          <ZoneCanvas
            imageUrl={frame.state === 'ready' ? frame.url : null}
            zones={draft.zones}
            selectedZone={selectedZone}
            selectedPoint={selectedPoint}
            editable={editable}
            onSelectZone={(id) => {
              setSelectedZone(id)
              setSelectedPoint(null)
            }}
            onSelectPoint={setSelectedPoint}
            onAddPoint={(p) => {
              if (!zone) return
              edit((d) => addPoint(d, zone.id, p))
              setSelectedPoint(zone.polygon.length)
            }}
            onMovePoint={(i, p, gesture) => zone && edit((d) => movePoint(d, zone.id, i, p), `move-${gesture}`)}
          />
        ) : (
          <div className="frame-state" role="status">
            {frame.state === 'loading' && <p>Загружаем кадр с камеры…</p>}
            {frame.state === 'empty' && <p>Камера ещё не передала изображение ({frame.detail}).</p>}
            {frame.state === 'error' && <p className="form-error">Кадр не загружен: {frame.message}</p>}
            {frame.state !== 'loading' && (
              <div className="frame-actions">
                <button type="button" className="btn" onClick={reload}>
                  Повторить
                </button>
                <button type="button" className="btn btn-ghost" onClick={() => setBlank(true)}>
                  {editable ? 'Размечать без кадра' : 'Показать зоны без кадра'}
                </button>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="step" aria-labelledby={`step3-${camera.id}`}>
        <div className="step-head">
          <span className="step-num" aria-hidden="true">
            3
          </span>
          <h4 id={`step3-${camera.id}`}>Правила</h4>
        </div>
        {specsError ? (
          <p className="form-error">Описания правил не загружены: {specsError}. Сохранение недоступно.</p>
        ) : (
          <RulesForm
            rules={draft.rules}
            specs={specs}
            zones={draft.zones}
            disabled={!editable}
            onAdd={(spec) => edit((d) => ({ ...d, rules: [...d.rules, newRule(spec)] }))}
            onRemove={(key) => edit((d) => ({ ...d, rules: d.rules.filter((r) => r.key !== key) }))}
            onChange={(key, update, field) =>
              edit((d) => ({ ...d, rules: d.rules.map((r) => (r.key === key ? update(r) : r)) }), `rule-${key}-${field}`)
            }
          />
        )}
      </section>

      {(dirty || save.state !== 'idle') && (
        <div className={dirty ? 'save-bar save-bar-dirty' : 'save-bar'}>
          <div className="save-status" role="status">
            {errors.length > 0 && dirty && editable && (
              <ul className="form-error">
                {errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            )}
            {save.state === 'saving' && <span>Сохраняем…</span>}
            {save.state === 'error' && (
              <div className="form-error" role="alert">
                <span>Не сохранено: {save.message}</span>
                {save.details.length > 0 && (
                  <ul>
                    {save.details.map((d) => (
                      <li key={d}>{d}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {save.state === 'saved' && !dirty && (
              <span className="save-ok">Сохранено в {timeFmt.format(save.at)}, камера уже работает с новыми настройками</span>
            )}
            {dirty && editable && save.state !== 'saving' && errors.length === 0 && <span className="muted">Есть несохранённые изменения</span>}
          </div>
          {dirty && (
            <button type="button" className="btn btn-ghost" onClick={resetDraft} disabled={save.state === 'saving'}>
              {editable ? 'Отменить изменения' : 'Вернуть как было'}
            </button>
          )}
          {editable && dirty && (
            <button type="button" className="btn btn-primary btn-lg" onClick={submit} disabled={!canSave}>
              {save.state === 'saving' ? 'Сохраняем…' : 'Сохранить'}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function pointsWord(n: number): string {
  const m10 = n % 10
  const m100 = n % 100
  if (m10 === 1 && m100 !== 11) return 'точку'
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return 'точки'
  return 'точек'
}

// Одна подсказка по текущему шагу разметки вместо общего списка инструкций
function contourHint(zoneName: string | null, points: number, hasZones: boolean, selectedPoint: number | null): string {
  if (zoneName === null) return hasZones ? 'Выберите зону в шаге 1.' : 'Сначала создайте зону в шаге 1.'
  if (points === 0) return `Зона «${zoneName}»: нажмите на кадр там, где начинается опасный участок.`
  if (points < MIN_POINTS) {
    const left = MIN_POINTS - points
    return `Поставьте ещё ${left} ${pointsWord(left)} по углам участка.`
  }
  if (points >= MAX_POINTS) return `Контур готов. Достигнут предел: ${MAX_POINTS} точек.`
  if (selectedPoint !== null) return `Выбрана точка ${selectedPoint + 1}: перетащите её или удалите.`
  return 'Контур готов. Точки можно перетаскивать, нажатие на кадр добавляет новую.'
}
