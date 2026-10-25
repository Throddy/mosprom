import { useEffect, useRef } from 'react'
import type { EventStatus, EventView } from '../api/types.ts'
import { SEVERITY_LABEL, STATUS_LABEL } from '../alerts/feed.ts'
import { formatDuration, formatFull, zoneLabel } from '../alerts/format.ts'
import { navigate, routeHref } from '../router.ts'
import { Snapshot } from './Snapshot.tsx'
import { StatusActions } from './StatusActions.tsx'

interface Props {
  // null: события нет среди загруженных
  event: EventView | null
  eventId: string
  pending: EventStatus | undefined
  error: string | undefined
  // сервер в тестовом режиме: событие не от нейросети
  testMode: boolean
  onStatus: (event: EventView, status: EventStatus) => void
  onClose: () => void
}

// Детали события из уже загруженного EventView, без отдельного запроса
export function EventDetails({ event, eventId, pending, error, testMode, onStatus, onClose }: Props) {
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
        <h2 id="details-title">{event ? (event.title ?? event.type) : 'Тревога'}</h2>
        <button type="button" className="btn btn-lg" onClick={onClose} autoFocus>
          Закрыть
        </button>
      </div>
      {event ? (
        <DetailsBody event={event} pending={pending} error={error} testMode={testMode} onStatus={onStatus} />
      ) : (
        <NotLoaded id={eventId} />
      )}
    </dialog>
  )
}

function NotLoaded({ id }: { id: string }) {
  return (
    <div className="details-missing">
      <p>Эта тревога не найдена среди загруженных. Найдите её в журнале по камере и времени.</p>
      <p className="muted small">
        Номер тревоги: <code>{id}</code>
      </p>
      <a className="btn" href={routeHref('journal')}>
        Открыть журнал
      </a>
    </div>
  )
}

type BodyProps = Omit<Props, 'event' | 'eventId' | 'onClose'> & { event: EventView }

function DetailsBody({ event, pending, error, testMode, onStatus }: BodyProps) {
  const zone = zoneLabel(event)
  const extra = Object.entries(event.extra ?? {})

  return (
    <div className="details-body" data-event-id={event.id}>
      <div className="details-media">
        <Snapshot url={event.snapshot_url} title={event.title ?? event.type} className="details-snap" />
        {event.snapshot_url && <p className="muted small">Нажмите на кадр, чтобы открыть его в полном размере.</p>}
      </div>

      <div className="details-info">
        <div className="tags">
          <span className={`badge badge-${event.severity}`}>{SEVERITY_LABEL[event.severity] ?? event.severity}</span>
          <span className={`chip chip-${event.status}`}>{STATUS_LABEL[event.status] ?? event.status}</span>
          {testMode && <span className="tag-test">Тестовое событие</span>}
        </div>

        <dl className="facts">
          <dt>Камера</dt>
          <dd>{event.camera_name ?? event.camera_id}</dd>
          <dt>Зона</dt>
          <dd className={zone ? undefined : 'muted'}>{zone ?? 'весь кадр'}</dd>
          <dt>Тревога</dt>
          <dd>{formatFull(event.ts_confirm)}</dd>
          <dt>Длительность</dt>
          <dd>
            {event.ts_end === null
              ? `продолжается, началось ${formatFull(event.ts_start)}`
              : `${formatDuration(event.ts_end - event.ts_start)}, до ${formatFull(event.ts_end)}`}
          </dd>
          {event.comment && (
            <>
              <dt>Комментарий</dt>
              <dd>{event.comment}</dd>
            </>
          )}
          {event.clip_url && (
            <>
              <dt>Видео</dt>
              <dd>
                <a href={event.clip_url} target="_blank" rel="noreferrer">
                  Открыть фрагмент
                </a>
              </dd>
            </>
          )}
        </dl>

        <StatusActions event={event} pending={pending} error={error} onStatus={onStatus} />

        <div className="details-links">
          <button
            type="button"
            className="btn"
            onClick={() =>
              // В мониторе только эта камера; back — адрес окна тревоги для возврата
              navigate(routeHref('monitor', { cams: event.camera_id, layout: '1', focus: event.camera_id, back: window.location.hash }))
            }
          >
            Показать камеру
          </button>
          <a href={routeHref('journal', { camera_id: event.camera_id })}>Все тревоги камеры в журнале</a>
        </div>

        <details className="more">
          <summary>Технические данные</summary>
          <dl className="facts facts-small">
            <dt>Тип</dt>
            <dd>
              <code>{event.type}</code>
            </dd>
            <dt>Камера</dt>
            <dd>
              <code>{event.camera_id}</code>
            </dd>
            <dt>Начало</dt>
            <dd>{formatFull(event.ts_start)}</dd>
            <dt>Трек</dt>
            <dd>{event.track_id}</dd>
            <dt>Уверенность</dt>
            <dd>{event.conf.toFixed(2)}</dd>
            <dt>Рамка, px</dt>
            <dd>{event.bbox.map((v) => Math.round(v)).join(', ')}</dd>
            {extra.length > 0 && (
              <>
                <dt>Данные правила</dt>
                <dd>
                  <code className="extra">{JSON.stringify(event.extra)}</code>
                </dd>
              </>
            )}
            <dt>id</dt>
            <dd>
              <code>{event.id}</code>
            </dd>
          </dl>
        </details>
      </div>
    </div>
  )
}
