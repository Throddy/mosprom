import type { EventStatus, EventView } from '../api/types.ts'
import { ACTIONS, STATUS_LABEL } from '../alerts/feed.ts'

interface Props {
  event: EventView
  pending: EventStatus | undefined
  error: string | undefined
  onStatus: (event: EventView, status: EventStatus) => void
}

// Кнопки решения оператора: PATCH /api/events/{id}
export function StatusActions({ event, pending, error, onStatus }: Props) {
  return (
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
  )
}
