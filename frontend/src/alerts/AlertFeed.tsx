import { useMemo, useState } from 'react'
import { EventDetails } from '../components/EventDetails.tsx'
import { AlertCard } from './AlertCard.tsx'
import { sortFeed } from './feed.ts'
import type { AlertFeed as Feed, Connection } from './useAlertFeed.ts'

type View = 'all' | 'new'

export function AlertFeed({ feed }: { feed: Feed }) {
  const [view, setView] = useState<View>('all')
  const [detailsId, setDetailsId] = useState<string | null>(null)

  const sorted = useMemo(() => sortFeed(feed.events), [feed.events])
  const unhandled = useMemo(() => sorted.filter((e) => e.status === 'new'), [sorted])
  const unhandledCritical = unhandled.filter((e) => e.severity === 'critical').length
  const shown = view === 'new' ? unhandled : sorted

  return (
    <section className="feed" aria-labelledby="feed-title">
      <div className="feed-bar">
        <div className="feed-heading">
          <h2 id="feed-title">Лента тревог</h2>
          <ConnectionState connection={feed.connection} />
        </div>
        <div className="feed-counters">
          <span>
            Необработанных: <strong>{unhandled.length}</strong>
          </span>
          {unhandledCritical > 0 && (
            <span className="counter-critical">
              критичных: <strong>{unhandledCritical}</strong>
            </span>
          )}
        </div>
        <div className="segmented" role="group" aria-label="Показать">
          <button type="button" aria-pressed={view === 'all'} onClick={() => setView('all')}>
            Все ({sorted.length})
          </button>
          <button type="button" aria-pressed={view === 'new'} onClick={() => setView('new')}>
            Необработанные ({unhandled.length})
          </button>
        </div>
      </div>

      {feed.loadError && (
        <div className="notice notice-error" role="alert">
          <span>Не удалось загрузить события: {feed.loadError}</span>
          <button type="button" className="btn" onClick={feed.reload}>
            Повторить
          </button>
        </div>
      )}

      {!feed.loaded && !feed.loadError ? (
        <p className="feed-empty muted">Загрузка событий…</p>
      ) : shown.length === 0 ? (
        feed.loaded && (
          <p className="feed-empty muted">{view === 'new' ? 'Необработанных тревог нет' : 'Тревог нет'}</p>
        )
      ) : (
        <div className="feed-list">
          {shown.map((event) => (
            <AlertCard
              key={event.id}
              event={event}
              fresh={event.id in feed.fresh}
              pending={feed.pending[event.id]}
              error={feed.actionErrors[event.id]}
              onStatus={feed.setStatus}
              onDetails={(e) => setDetailsId(e.id)}
            />
          ))}
        </div>
      )}

      {detailsId && (
        <EventDetails
          eventId={detailsId}
          event={feed.events[detailsId] ?? null}
          pending={feed.pending[detailsId]}
          error={feed.actionErrors[detailsId]}
          onStatus={feed.setStatus}
          onClose={() => setDetailsId(null)}
        />
      )}
    </section>
  )
}

export function ConnectionState({ connection }: { connection: Connection }) {
  if (connection.state === 'open') {
    return (
      <span className="conn">
        <span className="dot dot-on" /> обновляется в реальном времени
      </span>
    )
  }
  if (connection.state === 'connecting') {
    return (
      <span className="conn muted">
        <span className="dot dot-wait" /> подключение к <code>/ws/events</code>…
      </span>
    )
  }
  return (
    <span className="conn conn-off" role="status">
      <span className="dot dot-off" /> нет связи с <code>/ws/events</code>, повтор через {connection.retryInSec} с
    </span>
  )
}
