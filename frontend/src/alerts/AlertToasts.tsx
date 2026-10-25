import { useCallback, useEffect, useRef, useState } from 'react'
import type { EventView, WsMessage } from '../api/types.ts'
import { navigate, routeHref } from '../router.ts'
import { formatTs } from './format.ts'
import type { FeedEvents } from './feed.ts'
import { shouldNotify, type NotifySettings } from './notifySettings.ts'

interface Props {
  subscribe: (listener: (msg: WsMessage) => void) => () => void
  events: FeedEvents
  // в разделе «Тревоги» новые тревоги и так видны сверху списка
  suppressed: boolean
  settings: NotifySettings
}

const NORMAL_MS = 8000
const CRITICAL_MS = 20000
// Видно одно уведомление в одну строку; остальные — ссылкой «ещё N» в нём.
// Так уведомление не доходит до кнопок под заголовком страницы и до видео
const VISIBLE = 1

// Уведомления только по живому event_new из /ws/events. Тревоги из GET (первая загрузка,
// перезагрузка страницы, синхронизация после переподключения) уведомлений не создают.
// Настройки скрывают только всплывающие окна: лента и счётчики получают тревоги всегда
export function AlertToasts({ subscribe, events, suppressed, settings }: Props) {
  const [toasts, setToasts] = useState<EventView[]>([])
  const known = useRef(events)
  const seen = useRef(new Set<string>())
  const timers = useRef(new Map<string, number>())
  const suppressedRef = useRef(suppressed)
  const settingsRef = useRef(settings)

  useEffect(() => {
    known.current = events
  }, [events])
  useEffect(() => {
    suppressedRef.current = suppressed
    if (suppressed) setToasts([])
  }, [suppressed])
  // Выключение или «только критические» сразу убирают лишние уведомления с экрана
  useEffect(() => {
    settingsRef.current = settings
    setToasts((list) => list.filter((t) => shouldNotify(settings, t.severity)))
  }, [settings])

  const dismiss = useCallback((id: string) => {
    window.clearTimeout(timers.current.get(id))
    timers.current.delete(id)
    setToasts((list) => list.filter((t) => t.id !== id))
  }, [])

  useEffect(
    () =>
      subscribe((msg) => {
        const e = msg.event
        // событие уже было в ленте до этого сообщения: не новое для оператора
        if (msg.kind !== 'event_new' || seen.current.has(e.id) || e.id in known.current) return
        seen.current.add(e.id)
        if (suppressedRef.current || !shouldNotify(settingsRef.current, e.severity)) return
        setToasts((list) => [e, ...list.filter((t) => t.id !== e.id)])
        const timer = window.setTimeout(() => dismiss(e.id), e.severity === 'critical' ? CRITICAL_MS : NORMAL_MS)
        timers.current.set(e.id, timer)
      }),
    [subscribe, dismiss],
  )

  useEffect(() => {
    const all = timers.current
    return () => all.forEach((t) => window.clearTimeout(t))
  }, [])

  const dismissAll = () => {
    timers.current.forEach((t) => window.clearTimeout(t))
    timers.current.clear()
    setToasts([])
  }

  const visible = toasts.slice(0, VISIBLE)
  const rest = toasts.length - visible.length

  return (
    <div className="toasts" aria-live="polite" aria-label="Уведомления о новых тревогах">
      {visible.map((e) => (
        <div key={e.id} className={`toast toast-${e.severity}`} data-event-id={e.id}>
          <div className="toast-body">
            <p className="toast-title">
              {/* критичность видна по красной полосе и фону, словом — для экранного диктора */}
              {e.severity === 'critical' && <span className="sr-only">Критично: </span>}
              {e.title ?? e.type}
            </p>
            <p className="toast-meta">
              {e.camera_name ?? e.camera_id} · {formatTs(e.ts_confirm)}
              {rest > 0 && (
                <>
                  {' · '}
                  <button
                    type="button"
                    className="toast-more"
                    onClick={() => {
                      dismissAll()
                      navigate(routeHref('alerts'))
                    }}
                  >
                    ещё {rest}
                  </button>
                </>
              )}
            </p>
          </div>
          <button
            type="button"
            className="btn btn-sm btn-primary toast-open"
            onClick={() => {
              dismiss(e.id)
              navigate(routeHref('alerts', { event: e.id }))
            }}
          >
            Посмотреть
          </button>
          <button type="button" className="toast-close" onClick={() => dismiss(e.id)} aria-label="Закрыть уведомление">
            ×
          </button>
        </div>
      ))}
    </div>
  )
}
