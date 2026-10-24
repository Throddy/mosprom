import { useEffect, useRef } from 'react'
import type { EventStatus, EventView } from '../api/types.ts'
import { SEVERITY_LABEL, STATUS_LABEL } from '../alerts/feed.ts'
import { formatDuration, formatFull, zoneLabel } from '../alerts/format.ts'
import { routeHref } from '../router.ts'
import { Snapshot } from './Snapshot.tsx'
import { StatusActions } from './StatusActions.tsx'

interface Props {
  // null: события нет среди загруженных
  event: EventView | null
  eventId: string
  pending: EventStatus | undefined
  error: string | undefined
  onStatus: (event: EventView, status: EventStatus) => void
  onClose: () => void
}

// Детали события из уже загруженного EventView, без отдельного запроса
export function EventDetails({ event, eventId, pending, error, onStatus, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null)

  // Без close() при размонтировании: элемент удаляется из DOM вместе с окном, а отложенное
  // событие close от повторного монтирования в StrictMode закрыло бы окно сразу после открытия
  useEffect(() => {
    const dialog = ref.current
    if (dialog && !dialog.open) dialog.showModal()
  }, [])

  return (
    <dialog
      ref={ref}
      className="details"
      aria-labelledby="details-title"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose()
      }}
    >
      <div className="details-head">
        <h2 id="details-title">{event ? (event.title ?? event.type) : 'Событие'}</h2>
        <button type="button" className="btn" onClick={onClose} autoFocus>
          Закрыть
        </button>
      </div>
      {event ? <DetailsBody event={event} pending={pending} error={error} onStatus={onStatus} /> : <NotLoaded id={eventId} />}
    </dialog>
  )
}

function NotLoaded({ id }: { id: string }) {
  return (
    <p className="muted">
      Событие <code>{id}</code> не найдено среди загруженных. Отдельного запроса события по id в API нет: найдите его в
      журнале по фильтрам.
    </p>
  )
}

function DetailsBody({ event, pending, error, onStatus }: Omit<Props, 'event' | 'eventId' | 'onClose'> & { event: EventView }) {
  const zone = zoneLabel(event)
  const extra = Object.entries(event.extra ?? {})

  return (
    <div className="details-body" data-event-id={event.id}>
      <Snapshot url={event.snapshot_url} title={event.title ?? event.type} className="details-snap" />

      <div>
        <div className="alert-head">
          <span className={`badge badge-${event.severity}`}>{SEVERITY_LABEL[event.severity] ?? event.severity}</span>
          <span className={`chip chip-${event.status}`}>{STATUS_LABEL[event.status] ?? event.status}</span>
        </div>

        <dl className="details-meta">
          <dt>Тип</dt>
          <dd>
            {event.title ?? event.type} <code className="muted">{event.type}</code>
          </dd>
          <dt>Камера</dt>
          <dd>
            {event.camera_name ?? event.camera_id} <code className="muted">{event.camera_id}</code>
          </dd>
          <dt>Зона</dt>
          <dd className={zone ? undefined : 'muted'}>{zone ?? 'не задана'}</dd>
          <dt>Начало</dt>
          <dd>{formatFull(event.ts_start)}</dd>
          <dt>Тревога</dt>
          <dd>{formatFull(event.ts_confirm)}</dd>
          <dt>Окончание</dt>
          <dd>
            {event.ts_end === null
              ? 'продолжается'
              : `${formatFull(event.ts_end)} · длительность ${formatDuration(event.ts_end - event.ts_start)}`}
          </dd>
          <dt>Трек</dt>
          <dd>{event.track_id}</dd>
          <dt>conf</dt>
          <dd>{event.conf.toFixed(2)}</dd>
          <dt>Бокс, px</dt>
          <dd>{event.bbox.map((v) => Math.round(v)).join(', ')}</dd>
          {extra.length > 0 && (
            <>
              <dt>Данные правила</dt>
              <dd>
                <code className="extra">{JSON.stringify(event.extra)}</code>
              </dd>
            </>
          )}
          <dt>Комментарий</dt>
          <dd className={event.comment ? undefined : 'muted'}>{event.comment ?? 'нет'}</dd>
          {event.clip_url && (
            <>
              <dt>Клип</dt>
              <dd>
                <a href={event.clip_url} target="_blank" rel="noreferrer">
                  открыть
                </a>
              </dd>
            </>
          )}
          <dt>id</dt>
          <dd>
            <code>{event.id}</code>
          </dd>
        </dl>

        <p className="details-links">
          <a href={routeHref('journal', { camera_id: event.camera_id })}>Все события камеры в журнале</a>
        </p>

        <StatusActions event={event} pending={pending} error={error} onStatus={onStatus} />
      </div>
    </div>
  )
}
