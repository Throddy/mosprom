import { useMemo } from 'react'
import { isTestMode } from '../api/source.ts'
import type { ServerStatus } from '../api/useServerStatus.ts'
import { EventDetails } from '../components/EventDetails.tsx'
import { navigate, routeHref } from '../router.ts'
import { AlertCard } from './AlertCard.tsx'
import { sortFeed } from './feed.ts'
import type { AlertFeed as Feed, Connection } from './useAlertFeed.ts'
import { useNow } from './useNow.ts'

interface Props {
  feed: Feed
  params: URLSearchParams
  server: ServerStatus
}

// Вид и открытая тревога хранятся в адресе: ?show=all, ?event=<id>. Ссылки с обзора открывают тревогу сразу,
// кнопка «Назад» телефона закрывает окно
export function AlertFeed({ feed, params, server }: Props) {
  const showAll = params.get('show') === 'all'
  const detailsId = params.get('event')
  const now = useNow()
  const testMode = isTestMode(server)

  const sorted = useMemo(() => sortFeed(feed.events), [feed.events])
  const unhandled = useMemo(() => sorted.filter((e) => e.status === 'new'), [sorted])
  const unhandledCritical = unhandled.filter((e) => e.severity === 'critical').length
  const shown = showAll ? sorted : unhandled
  // Всего новых на сервере: загруженные и те, что за пределами окна ленты
  const newTotal = unhandled.length + feed.hiddenNew

  const href = (next: { all?: boolean; event?: string | null }) => {
    const p: Record<string, string> = {}
    if (next.all ?? showAll) p.show = 'all'
    const ev = next.event === undefined ? detailsId : next.event
    if (ev) p.event = ev
    return routeHref('alerts', p)
  }

  return (
    <section className="page" aria-labelledby="feed-title">
      <div className="page-head">
        <div>
          <h2 id="feed-title">Тревоги</h2>
          <ConnectionState connection={feed.connection} />
        </div>
      </div>

      <p className="page-lead">
        {newTotal === 0 ? (
          'Новых тревог нет.'
        ) : (
          <>
            Ждут решения: <strong>{newTotal}</strong>
            {unhandledCritical > 0 && (
              <>
                , {feed.hiddenNew > 0 ? 'критичных среди показанных' : 'из них критичных'}:{' '}
                <strong className="text-danger">{unhandledCritical}</strong>
              </>
            )}
          </>
        )}
      </p>

      <div className="segmented" role="group" aria-label="Какие тревоги показать">
        <button type="button" aria-pressed={!showAll} onClick={() => navigate(href({ all: false }), true)}>
          Новые ({unhandled.length})
        </button>
        <button type="button" aria-pressed={showAll} onClick={() => navigate(href({ all: true }), true)}>
          Все ({sorted.length})
        </button>
      </div>

      {feed.hiddenNew > 0 && !showAll && (
        <div className="notice notice-info" role="status">
          <span>
            Показаны последние {unhandled.length}. Ещё {feed.hiddenNew} более ранних новых тревог в журнале.
          </span>
          <a className="btn btn-sm" href={routeHref('journal', { status: 'new' })}>
            Открыть журнал
          </a>
        </div>
      )}

      {feed.loadError && (
        <div className="notice notice-error" role="alert">
          <span>Не удалось загрузить тревоги: {feed.loadError}</span>
          <button type="button" className="btn" onClick={feed.reload}>
            Повторить
          </button>
        </div>
      )}

      {!feed.loaded && !feed.loadError ? (
        <p className="empty">Загружаем тревоги…</p>
      ) : shown.length === 0 ? (
        feed.loaded && (
          <div className="empty">
            <p className="empty-title">{showAll ? 'Тревог пока не было' : 'Новых тревог нет'}</p>
            <p className="muted">Система следит за камерами. Новая тревога появится здесь автоматически.</p>
            {!showAll && sorted.length > 0 && (
              <button type="button" className="btn" onClick={() => navigate(href({ all: true }), true)}>
                Показать разобранные ({sorted.length})
              </button>
            )}
          </div>
        )
      ) : (
        <div className="alert-list">
          {shown.map((event) => (
            <AlertCard
              key={event.id}
              event={event}
              fresh={event.id in feed.fresh}
              pending={feed.pending[event.id]}
              error={feed.actionErrors[event.id]}
              testMode={testMode}
              now={now}
              onStatus={feed.setStatus}
              onDetails={(e) => navigate(href({ event: e.id }))}
            />
          ))}
        </div>
      )}

      {detailsId && (feed.loaded || detailsId in feed.events) && (
        <EventDetails
          key={detailsId}
          eventId={detailsId}
          event={feed.events[detailsId] ?? null}
          pending={feed.pending[detailsId]}
          error={feed.actionErrors[detailsId]}
          testMode={testMode}
          onStatus={feed.setStatus}
          onClose={() => navigate(href({ event: null }), true)}
        />
      )}
    </section>
  )
}

export function ConnectionState({ connection }: { connection: Connection }) {
  if (connection.state === 'open') {
    return (
      <p className="conn">
        <span className="dot dot-on" aria-hidden="true" /> Обновляется автоматически
      </p>
    )
  }
  if (connection.state === 'connecting') {
    return (
      <p className="conn muted">
        <span className="dot dot-wait" aria-hidden="true" /> Подключаемся к серверу…
      </p>
    )
  }
  return (
    <p className="conn conn-off" role="status">
      <span className="dot dot-off" aria-hidden="true" /> Нет связи, новые тревоги не приходят. Повтор через {connection.retryInSec} с
    </p>
  )
}
