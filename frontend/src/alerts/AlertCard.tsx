import type { EventStatus, EventView } from '../api/types.ts'
import { Snapshot } from '../components/Snapshot.tsx'
import { StatusActions } from '../components/StatusActions.tsx'
import { SEVERITY_LABEL, STATUS_LABEL } from './feed.ts'
import { formatDuration, formatTs, zoneLabel } from './format.ts'

interface Props {
  event: EventView
  fresh: boolean
  pending: EventStatus | undefined
  error: string | undefined
  onStatus: (event: EventView, status: EventStatus) => void
  onDetails: (event: EventView) => void
}

export function AlertCard({ event, fresh, pending, error, onStatus, onDetails }: Props) {
  const zone = zoneLabel(event)
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
        <button type="button" className="link-btn" onClick={() => onDetails(event)}>
          Подробнее
        </button>
      </div>

      <StatusActions event={event} pending={pending} error={error} onStatus={onStatus} />
    </article>
  )
}
