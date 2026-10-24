import { useEffect, useMemo, useState } from 'react'
import { AlertCard } from './AlertCard.tsx'
import { sortFeed } from './feed.ts'
import { useAlertFeed, type Connection } from './useAlertFeed.ts'

type View = 'all' | 'new'

const BASE_TITLE = document.title

export function AlertFeed() {
  const feed = useAlertFeed()
  const [view, setView] = useState<View>('all')

  const sorted = useMemo(() => sortFeed(feed.events), [feed.events])
  const unhandled = useMemo(() => sorted.filter((e) => e.status === 'new'), [sorted])
  const unhandledCritical = unhandled.filter((e) => e.severity === 'critical').length
  const shown = view === 'new' ? unhandled : sorted

  useEffect(() => {
    document.title = unhandled.length ? `(${unhandled.length}) ${BASE_TITLE}` : BASE_TITLE
  }, [unhandled.length])

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
            />
          ))}
        </div>
      )}
    </section>
  )
}

function ConnectionState({ connection }: { connection: Connection }) {
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
