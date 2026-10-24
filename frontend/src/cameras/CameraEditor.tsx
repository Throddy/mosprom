import { useCallback, useEffect, useMemo, useReducer, useState } from 'react'
import { ApiError, errorText, putCamera } from '../api/client.ts'
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
      if (isTyping(e.target)) return
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
  }, [undo, deletePoint, selectedPoint])

  // Несохранённый черновик: подтверждение при уходе со страницы и переходах по разделам сайта
  useEffect(() => {
    if (!dirty) return
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
  }, [dirty])

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
        const details = err instanceof ApiError && err.detail ? err.detail.split('; ') : []
        setSave({ state: 'error', message: err instanceof ApiError ? `HTTP ${err.status}` : errorText(err), details })
      })
  }

  const canSave = dirty && errors.length === 0 && save.state !== 'saving' && !specsError
  const showCanvas = frame.state === 'ready' || blank

  return (
    <div className="editor" data-camera-id={camera.id}>
      <div className="editor-layout">
        <div className="editor-main">
          <div className="editor-toolbar" role="toolbar" aria-label="Разметка зон">
            <button type="button" className="btn btn-small" onClick={addZone}>
              Новая зона
            </button>
            <button type="button" className="btn btn-small" onClick={undo} disabled={history.past.length === 0} title="Ctrl+Z">
              Отменить
            </button>
            <button type="button" className="btn btn-small" onClick={deletePoint} disabled={selectedPoint === null} title="Delete">
              Удалить точку
            </button>
            <button type="button" className="btn btn-small" onClick={removeZone} disabled={!zone}>
              Удалить зону
            </button>
            {frame.state === 'ready' && (
              <button type="button" className="btn btn-small" onClick={reload}>
                Обновить кадр
              </button>
            )}
          </div>

          {showCanvas ? (
            <ZoneCanvas
              imageUrl={frame.state === 'ready' ? frame.url : null}
              zones={draft.zones}
              selectedZone={selectedZone}
              selectedPoint={selectedPoint}
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
              {frame.state === 'loading' && <p>Загрузка кадра…</p>}
              {frame.state === 'empty' && (
                <p>
                  Кадра ещё нет (503: {frame.detail}). Камера пока не передала изображение.
                </p>
              )}
              {frame.state === 'error' && <p className="form-error">Кадр не загружен: {frame.message}</p>}
              {frame.state !== 'loading' && (
                <div className="frame-actions">
                  <button type="button" className="btn" onClick={reload}>
                    Повторить
                  </button>
                  <button type="button" className="btn" onClick={() => setBlank(true)}>
                    Размечать без кадра
                  </button>
                </div>
              )}
            </div>
          )}

          <p className="editor-hint muted">
            {frame.state !== 'ready' && blank && 'Разметка без кадра: поле 16:9. '}
            {zone
              ? `Щелчок по кадру добавляет точку в зону «${zone.name}», точку можно перетащить. Точек: ${zone.polygon.length} из ${MAX_POINTS}, нужно не меньше ${MIN_POINTS}.`
              : 'Выберите зону в списке или создайте новую.'}
          </p>
          {notice && (
            <p className="form-error" role="alert">
              {notice}
            </p>
          )}
        </div>

        <aside className="editor-side" aria-label="Зоны камеры">
          <h4>Зоны</h4>
          {draft.zones.length === 0 && <p className="muted">Зон нет</p>}
          <ul className="zone-list">
            {draft.zones.map((z) => (
              <li key={z.id} className={z.id === selectedZone ? 'zone-item zone-item-active' : 'zone-item'} data-zone-id={z.id}>
                <label className="zone-pick">
                  <input
                    type="radio"
                    name={`zone-${camera.id}`}
                    checked={z.id === selectedZone}
                    onChange={() => {
                      setSelectedZone(z.id)
                      setSelectedPoint(null)
                    }}
                  />
                  <code className="muted">{z.id}</code>
                </label>
                <input
                  className="zone-name"
                  aria-label={`Название зоны ${z.id}`}
                  value={z.name}
                  maxLength={100}
                  onChange={(e) => edit((d) => updateZone(d, z.id, (x) => ({ ...x, name: e.target.value })), `name-${z.id}`)}
                />
                <span className={z.polygon.length < MIN_POINTS ? 'zone-points form-error' : 'zone-points muted'}>
                  точек: {z.polygon.length}
                </span>
              </li>
            ))}
          </ul>
        </aside>
      </div>

      <h4>Правила</h4>
      {specsError ? (
        <p className="form-error">Описания правил не загружены: {specsError}. Сохранение недоступно.</p>
      ) : (
        <RulesForm
          rules={draft.rules}
          specs={specs}
          zones={draft.zones}
          onAdd={(spec) => edit((d) => ({ ...d, rules: [...d.rules, newRule(spec)] }))}
          onRemove={(key) => edit((d) => ({ ...d, rules: d.rules.filter((r) => r.key !== key) }))}
          onChange={(key, update, field) =>
            edit((d) => ({ ...d, rules: d.rules.map((r) => (r.key === key ? update(r) : r)) }), `rule-${key}-${field}`)
          }
        />
      )}

      <div className="save-bar">
        <div className="save-status" role="status">
          {errors.length > 0 && dirty && (
            <ul className="form-error">
              {errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
          {save.state === 'saving' && <span>Сохранение…</span>}
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
            <span className="save-ok">Сохранено в {timeFmt.format(save.at)}, сервер применил изменения</span>
          )}
          {dirty && save.state !== 'saving' && errors.length === 0 && <span className="muted">Есть несохранённые изменения</span>}
        </div>
        <button type="button" className="btn" onClick={resetDraft} disabled={!dirty || save.state === 'saving'}>
          Сбросить изменения
        </button>
        <button type="button" className="btn btn-primary" onClick={submit} disabled={!canSave}>
          {save.state === 'saving' ? 'Сохранение…' : 'Сохранить'}
        </button>
      </div>
    </div>
  )
}
