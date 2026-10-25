import type { EventStatus, EventView } from '../api/types.ts'
import { Snapshot } from '../components/Snapshot.tsx'
import { StatusActions } from '../components/StatusActions.tsx'
import { SEVERITY_LABEL, STATUS_LABEL } from './feed.ts'
import { formatAgo, formatDuration, formatTs, zoneLabel } from './format.ts'

interface Props {
  event: EventView
  fresh: boolean
  pending: EventStatus | undefined
  error: string | undefined
  testMode: boolean
  now: number
  onStatus: (event: EventView, status: EventStatus) => void
  onDetails: (event: EventView) => void
}

export function AlertCard({ event, fresh, pending, error, testMode, now, onStatus, onDetails }: Props) {
  const zone = zoneLabel(event)
  const title = event.title ?? event.type
  const ago = formatAgo(event.ts_confirm, now)
  const classes = ['alert', `sev-${event.severity}`, `status-${event.status}`]
  if (fresh) classes.push('fresh')

  return (
    <article className={classes.join(' ')} data-event-id={event.id} aria-busy={pending !== undefined}>
      <Snapshot url={event.snapshot_url} title={title} className="alert-snap" onOpen={() => onDetails(event)} />

      <div className="alert-body">
        <div className="tags">
          <span className={`badge badge-${event.severity}`}>{SEVERITY_LABEL[event.severity] ?? event.severity}</span>
          {event.status !== 'new' && <span className={`chip chip-${event.status}`}>{STATUS_LABEL[event.status] ?? event.status}</span>}
          {fresh && <span className="tag-fresh">Только что</span>}
          {testMode && <span className="tag-test">тест</span>}
        </div>
        <h3 className="alert-title">
          <button type="button" className="title-btn" onClick={() => onDetails(event)}>
            {title}
          </button>
        </h3>
        <p className="alert-line">
          <span className="muted">Камера:</span> {event.camera_name ?? event.camera_id}
          {zone && (
            <>
              {' · '}
              <span className="muted">Зона:</span> {zone}
            </>
          )}
        </p>
        <p className="alert-line">
          <time dateTime={new Date(event.ts_confirm * 1000).toISOString()}>{formatTs(event.ts_confirm)}</time>
          {ago && <span className="muted"> · {ago}</span>}
          <span className="muted">
            {' · '}
            {event.ts_end === null ? 'продолжается' : `длилось ${formatDuration(event.ts_end - event.ts_start)}`}
          </span>
        </p>
        {event.comment && <p className="alert-line muted">Комментарий: {event.comment}</p>}
      </div>

      <StatusActions event={event} pending={pending} error={error} onStatus={onStatus} />
    </article>
  )
}
