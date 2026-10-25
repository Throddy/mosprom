import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { errorText, eventsPath, getEvents } from '../api/client.ts'
import type { EventView, WsMessage } from '../api/types.ts'
import { useCatalog } from '../api/useCatalog.ts'
import { SEVERITY_LABEL, STATUS_LABEL } from '../alerts/feed.ts'
import { formatAgo, formatTs, zoneLabel } from '../alerts/format.ts'
import { useNow } from '../alerts/useNow.ts'
import { isTestMode } from '../api/source.ts'
import type { ServerStatus } from '../api/useServerStatus.ts'
import { EventDetails } from '../components/EventDetails.tsx'
import { Snapshot } from '../components/Snapshot.tsx'
import { navigate, routeHref } from '../router.ts'
import { JournalFilters } from './JournalFilters.tsx'
import {
  LIMITS,
  hasFilters,
  journalParams,
  matchesFilters,
  pageCount,
  parseJournal,
  rangeError,
  toQuery,
  type JournalFilters as Filters,
  type JournalState,
} from './query.ts'
import { useStatusPatch } from './useStatusPatch.ts'

interface Props {
  params: URLSearchParams
  subscribe: (listener: (msg: WsMessage) => void) => () => void
  server: ServerStatus
}

interface Loaded {
  key: string
  items: EventView[]
  total: number
  at: number
}

const timeFmt = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

export function JournalPage({ params, subscribe, server }: Props) {
  const now = useNow()
  const testMode = isTestMode(server)
  const state = useMemo(() => parseJournal(params), [params])
  const catalog = useCatalog()
  const query = useMemo(() => toQuery(state), [state])
  const key = eventsPath(query)
  const invalid = rangeError(state)

  const [data, setData] = useState<Loaded | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [newCount, setNewCount] = useState(0)
  const [tick, setTick] = useState(0)

  const go = useCallback((next: JournalState, replace = false) => {
    navigate(routeHref('journal', journalParams(next)), replace)
  }, [])
  const setFilters = (patch: Partial<Filters>) => go({ ...state, ...patch, page: 1, event: undefined })

  // Запрос страницы: фильтры, limit и offset уходят на сервер
  useEffect(() => {
    if (invalid) {
      setLoading(false)
      return
    }
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    getEvents(query, controller.signal)
      .then((page) => {
        setData({ key, items: page.items, total: page.total, at: Date.now() })
        setNewCount(0)
        setLoading(false)
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        setError(errorText(err))
        setLoading(false)
      })
    return () => controller.abort()
    // query меняется вместе с key
  }, [key, tick, invalid])

  // Страница за пределами total (например, после удаления фильтра): переход на последнюю
  useEffect(() => {
    if (data && data.key === key && data.total > 0 && data.items.length === 0 && state.page > 1) {
      go({ ...state, page: pageCount(data.total, state.limit) }, true)
    }
  }, [data, key, state, go])

  // event_update меняет строку на странице; event_new по фильтрам только увеличивает счётчик,
  // чтобы строки не сдвигались под курсором оператора
  const filtersRef = useRef<Filters>(state)
  useEffect(() => {
    filtersRef.current = state
  }, [state])
  useEffect(
    () =>
      subscribe((msg) => {
        if (msg.kind === 'event_update') {
          setData((d) =>
            d && d.items.some((e) => e.id === msg.event.id)
              ? { ...d, items: d.items.map((e) => (e.id === msg.event.id ? msg.event : e)) }
              : d,
          )
        } else if (matchesFilters(msg.event, filtersRef.current)) {
          setNewCount((n) => n + 1)
        }
      }),
    [subscribe],
  )

  const onSaved = useCallback((view: EventView) => {
    setData((d) => d && { ...d, items: d.items.map((e) => (e.id === view.id ? view : e)) })
  }, [])
  const patch = useStatusPatch(onSaved)

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const pages = pageCount(total, state.limit)
  const first = total === 0 ? 0 : (state.page - 1) * state.limit + 1
  const last = Math.min(total, (state.page - 1) * state.limit + items.length)
  const stale = loading || (data !== null && data.key !== key)
  const details = state.event ? (items.find((e) => e.id === state.event) ?? null) : null

  return (
    <section className="page journal" aria-labelledby="journal-title">
      <div className="page-head">
        <div>
          <h2 id="journal-title">Журнал тревог</h2>
          <p className="muted journal-meta">
            {data && !invalid && (
              <>
                Найдено: <strong className="journal-total">{total}</strong> · обновлено {timeFmt.format(data.at)}
                {' · '}
              </>
            )}
            <button type="button" className="link-btn" onClick={() => setTick((t) => t + 1)} disabled={loading}>
              {loading ? 'загрузка…' : 'обновить'}
            </button>
          </p>
        </div>
      </div>

      <JournalFilters
        filters={state}
        catalog={catalog}
        onChange={setFilters}
        onReset={() => go({ page: 1, limit: state.limit })}
      />

      {newCount > 0 && !invalid && (
        <div className="notice notice-info" role="status">
          <span>Новых тревог по этим фильтрам: {newCount}</span>
          <button type="button" className="btn" onClick={() => (state.page === 1 ? setTick((t) => t + 1) : go({ ...state, page: 1 }))}>
            Показать
          </button>
        </div>
      )}

      {invalid && (
        <div className="notice notice-error" role="alert">
          {invalid}. Исправьте даты в фильтрах.
        </div>
      )}

      {error && !invalid && (
        <div className="notice notice-error" role="alert">
          <span>Не удалось загрузить журнал: {error}</span>
          <button type="button" className="btn" onClick={() => setTick((t) => t + 1)}>
            Повторить
          </button>
        </div>
      )}

      {invalid ? null : data === null ? (
        loading && <p className="empty">Загружаем журнал…</p>
      ) : items.length === 0 ? (
        !stale && (
          <div className="empty">
            <p className="empty-title">{hasFilters(state) ? 'По выбранным фильтрам тревог нет' : 'Тревог пока не было'}</p>
            {hasFilters(state) && (
              <button type="button" className="btn" onClick={() => go({ page: 1, limit: state.limit })}>
                Сбросить фильтры
              </button>
            )}
          </div>
        )
      ) : (
        <div className="table-wrap journal-wrap" aria-busy={stale}>
          <table className={`journal-table${stale ? ' stale' : ''}`}>
            <thead>
              <tr>
                <th scope="col">Кадр</th>
                <th scope="col">Нарушение</th>
                <th scope="col">Время</th>
                <th scope="col">Камера и зона</th>
                <th scope="col">Решение</th>
                <th scope="col">
                  <span className="sr-only">Действия</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((e) => {
                const zone = zoneLabel(e)
                const title = e.title ?? e.type
                const open = () => go({ ...state, event: e.id })
                const ago = formatAgo(e.ts_confirm, now)
                return (
                  <tr key={e.id} data-event-id={e.id} className={`row-${e.severity}`}>
                    <td className="cell-snap">
                      <Snapshot url={e.snapshot_url} title={title} className="row-snap" onOpen={open} />
                    </td>
                    <td className="cell-title">
                      <span className="row-title">{title}</span>
                      <span className="tags">
                        <span className={`badge badge-${e.severity}`}>{SEVERITY_LABEL[e.severity] ?? e.severity}</span>
                        {testMode && <span className="tag-test">Тест</span>}
                      </span>
                    </td>
                    <td className="cell-time">
                      <time dateTime={new Date(e.ts_confirm * 1000).toISOString()}>{formatTs(e.ts_confirm)}</time>
                      {ago && <span className="muted"> · {ago}</span>}
                    </td>
                    <td className="cell-place">
                      {e.camera_name ?? e.camera_id}
                      {zone && <span className="muted"> · {zone}</span>}
                    </td>
                    <td className="cell-status">
                      <span className={`chip chip-${e.status}`}>{STATUS_LABEL[e.status] ?? e.status}</span>
                    </td>
                    <td className="cell-open">
                      <button type="button" className="btn btn-ghost" onClick={open}>
                        Открыть
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {data !== null && total > 0 && !invalid && (
        <nav className="pager" aria-label="Страницы журнала">
          <span className="muted pager-range">
            {first}–{last} из {total}
          </span>
          <div className="pager-buttons">
            <button
              type="button"
              className="btn pager-edge"
              disabled={state.page <= 1}
              onClick={() => go({ ...state, page: 1 })}
              aria-label="Первая страница"
            >
              «
            </button>
            <button type="button" className="btn" disabled={state.page <= 1} onClick={() => go({ ...state, page: state.page - 1 })}>
              ‹ Назад
            </button>
            <span className="pager-page">
              {state.page} из {pages}
            </span>
            <button
              type="button"
              className="btn"
              disabled={state.page >= pages}
              onClick={() => go({ ...state, page: state.page + 1 })}
            >
              Вперёд ›
            </button>
            <button
              type="button"
              className="btn pager-edge"
              disabled={state.page >= pages}
              onClick={() => go({ ...state, page: pages })}
              aria-label="Последняя страница"
            >
              »
            </button>
          </div>
          <label className="pager-limit">
            <span className="muted">По</span>
            <select value={state.limit} onChange={(e) => go({ ...state, limit: Number(e.target.value), page: 1 })}>
              {LIMITS.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </label>
        </nav>
      )}

      {state.event && !stale && (
        <EventDetails
          key={state.event}
          eventId={state.event}
          event={details}
          pending={patch.pending[state.event]}
          error={patch.errors[state.event]}
          testMode={testMode}
          onStatus={patch.setStatus}
          onClose={() => go({ ...state, event: undefined }, true)}
        />
      )}
    </section>
  )
}
