import { useState } from 'react'
import type { EventStatus, EventView } from '../api/types.ts'
import { ACTIONS, SEVERITY_LABEL, STATUS_LABEL } from './feed.ts'
import { formatDuration, formatTs } from './format.ts'

interface Props {
  event: EventView
  fresh: boolean
  pending: EventStatus | undefined
  error: string | undefined
  onStatus: (event: EventView, status: EventStatus) => void
}

export function AlertCard({ event, fresh, pending, error, onStatus }: Props) {
  const zone = event.zone_name ?? event.zone_id
  const classes = ['alert', `sev-${event.severity}`, `status-${event.status}`]
  if (fresh) classes.push('fresh')

  return (
    <article className={classes.join(' ')} data-event-id={event.id} aria-busy={pending !== undefined}>
      <Snapshot url={event.snapshot_url} title={event.title ?? event.type} />

      <div className="alert-body">
        <div className="alert-head">
          <span className={`badge badge-${event.severity}`}>
            {SEVERITY_LABEL[event.severity] ?? event.severity}
          </span>
          <h3>{event.title ?? event.type}</h3>
          <span className={`chip chip-${event.status}`}>{STATUS_LABEL[event.status] ?? event.status}</span>
        </div>

        <dl className="alert-meta">
          <dt>Камера</dt>
          <dd>{event.camera_name ?? event.camera_id}</dd>
          <dt>Зона</dt>
          <dd className={zone ? undefined : 'muted'}>{zone ?? 'не задана'}</dd>
          <dt>Время</dt>
          <dd>
            <time dateTime={new Date(event.ts_confirm * 1000).toISOString()}>{formatTs(event.ts_confirm)}</time>
            <span className="muted">
              {' · '}
              {event.ts_end === null
                ? 'продолжается'
                : `длительность ${formatDuration(event.ts_end - event.ts_start)}`}
            </span>
          </dd>
          {event.comment && (
            <>
              <dt>Комментарий</dt>
              <dd>{event.comment}</dd>
            </>
          )}
        </dl>
      </div>

      <div className="alert-actions" role="group" aria-label="Решение оператора">
        {ACTIONS.map((status) => {
          const current = event.status === status
          return (
            <button
              key={status}
              type="button"
              className={`btn btn-${status}`}
              aria-pressed={current}
              disabled={current || pending !== undefined}
              onClick={() => onStatus(event, status)}
            >
              {pending === status ? 'Сохранение…' : STATUS_LABEL[status]}
            </button>
          )
        })}
        {error && (
          <p className="alert-error" role="alert">
            Статус не сохранён: {error}
          </p>
        )}
      </div>
    </article>
  )
}

function Snapshot({ url, title }: { url: string | null; title: string }) {
  const [failed, setFailed] = useState(false)
  if (!url || failed) {
    return <div className="alert-snap alert-snap-empty">Снимка нет</div>
  }
  return (
    <a className="alert-snap" href={url} target="_blank" rel="noreferrer" title="Открыть снимок">
      <img src={url} alt={`Снимок: ${title}`} loading="lazy" onError={() => setFailed(true)} />
    </a>
  )
}
