import { useCallback, useEffect, useRef, useState } from 'react'
import { eventsSocketUrl, getEvents, patchEvent } from '../api/client.ts'
import type { EventStatus, EventView, WsMessage } from '../api/types.ts'
import { applyMessage, parseMessage, upsert, type FeedEvents } from './feed.ts'

const SYNC_LIMIT = 100
const RETRY_MIN_MS = 1000
const RETRY_MAX_MS = 15000
const FRESH_MS = 10000

export type Connection =
  | { state: 'connecting' }
  | { state: 'open' }
  | { state: 'closed'; retryInSec: number }

export interface AlertFeed {
  events: FeedEvents
  loaded: boolean
  loadError: string | null
  connection: Connection
  pending: Record<string, EventStatus>
  actionErrors: Record<string, string>
  fresh: Record<string, true>
  setStatus: (event: EventView, status: EventStatus) => void
  reload: () => void
}

function without<T>(rec: Record<string, T>, key: string): Record<string, T> {
  if (!(key in rec)) return rec
  const next = { ...rec }
  delete next[key]
  return next
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

// Синхронизация: при каждом открытии WebSocket лента перечитывается через GET /api/events.
// Сообщения, пришедшие во время запроса, ставятся в очередь и применяются после ответа,
// поэтому снимок GET не затирает более новые изменения из WebSocket.
export function useAlertFeed(): AlertFeed {
  const [events, setEvents] = useState<FeedEvents>({})
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [connection, setConnection] = useState<Connection>({ state: 'connecting' })
  const [pending, setPending] = useState<Record<string, EventStatus>>({})
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({})
  const [fresh, setFresh] = useState<Record<string, true>>({})
  const syncRef = useRef<() => void>(() => {})

  useEffect(() => {
    let disposed = false
    let socket: WebSocket | null = null
    let retryTimer: number | undefined
    let attempt = 0
    let syncGen = 0
    let syncing = false
    let synced = false
    let queue: WsMessage[] = []
    let controller: AbortController | null = null
    const freshTimers = new Set<number>()

    const markFresh = (id: string) => {
      setFresh((f) => ({ ...f, [id]: true }))
      const timer = window.setTimeout(() => {
        freshTimers.delete(timer)
        setFresh((f) => without(f, id))
      }, FRESH_MS)
      freshTimers.add(timer)
    }

    const apply = (msg: WsMessage) => {
      setEvents((f) => applyMessage(f, msg))
      if (msg.kind === 'event_new') markFresh(msg.event.id)
    }

    const sync = () => {
      const gen = ++syncGen
      controller?.abort()
      controller = new AbortController()
      syncing = true
      getEvents(SYNC_LIMIT, controller.signal)
        .then((page) => {
          if (disposed || gen !== syncGen) return
          synced = true
          setEvents((f) => upsert(f, page.items))
          setLoadError(null)
          setLoaded(true)
        })
        .catch((err: unknown) => {
          if (disposed || gen !== syncGen) return
          setLoadError(errorText(err))
        })
        .finally(() => {
          if (disposed || gen !== syncGen) return
          syncing = false
          const queued = queue
          queue = []
          queued.forEach(apply)
        })
    }
    syncRef.current = sync

    const connect = () => {
      if (disposed) return
      setConnection({ state: 'connecting' })
      const ws = new WebSocket(eventsSocketUrl())
      socket = ws
      ws.onopen = () => {
        attempt = 0
        setConnection({ state: 'open' })
        sync()
      }
      ws.onmessage = (e: MessageEvent) => {
        const msg = parseMessage(e.data)
        if (!msg) return
        if (syncing) queue.push(msg)
        else apply(msg)
      }
      ws.onclose = () => {
        if (disposed || socket !== ws) return
        socket = null
        const delay = Math.min(RETRY_MIN_MS * 2 ** attempt, RETRY_MAX_MS)
        attempt += 1
        setConnection({ state: 'closed', retryInSec: Math.round(delay / 1000) })
        // Без WebSocket лента всё равно загружается через GET, но не обновляется сама
        if (!synced && !syncing) sync()
        retryTimer = window.setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      disposed = true
      window.clearTimeout(retryTimer)
      freshTimers.forEach((t) => window.clearTimeout(t))
      controller?.abort()
      if (socket?.readyState === WebSocket.CONNECTING) {
        // Закрытие до установки соединения браузер пишет в консоль как ошибку
        const ws = socket
        ws.onopen = () => ws.close()
      } else {
        socket?.close()
      }
    }
  }, [])

  const setStatus = useCallback((event: EventView, status: EventStatus) => {
    setPending((p) => ({ ...p, [event.id]: status }))
    setActionErrors((e) => without(e, event.id))
    patchEvent(event.id, status, event.comment)
      .then((view) => setEvents((f) => upsert(f, [view])))
      .catch((err: unknown) => setActionErrors((e) => ({ ...e, [event.id]: errorText(err) })))
      .finally(() => setPending((p) => without(p, event.id)))
  }, [])

  const reload = useCallback(() => syncRef.current(), [])

  return { events, loaded, loadError, connection, pending, actionErrors, fresh, setStatus, reload }
}
