import { useState } from 'react'
import { READ_ONLY_TITLE, useReadOnly } from '../api/readOnly.ts'
import type { EventStatus, EventView } from '../api/types.ts'
import { ACTION_LABEL, ACTIONS, STATUS_LABEL } from '../alerts/feed.ts'

interface Props {
  event: EventView
  pending: EventStatus | undefined
  error: string | undefined
  onStatus: (event: EventView, status: EventStatus) => void
}

// Решение оператора: PATCH /api/events/{id}. У новой тревоги кнопки видны сразу,
// у разобранной — после «Изменить решение». В режиме просмотра кнопок нет
export function StatusActions({ event, pending, error, onStatus }: Props) {
  const readOnly = useReadOnly()
  const [changing, setChanging] = useState(false)
  const decided = event.status !== 'new'
  const open = !decided || changing || pending !== undefined

  return (
    <div className="decision" role="group" aria-label="Решение оператора">
      {readOnly !== null ? (
        <p className="readonly-note">
          {READ_ONLY_TITLE}. Решение по тревоге здесь не сохраняется.
        </p>
      ) : open ? (
        <div className="decision-buttons">
          {ACTIONS.map((status) => {
            const current = event.status === status
            return (
              <button
                key={status}
                type="button"
                className={status === 'confirmed' ? 'btn btn-lg btn-primary' : 'btn btn-lg'}
                aria-pressed={current}
                disabled={current || pending !== undefined}
                onClick={() => {
                  setChanging(false)
                  onStatus(event, status)
                }}
              >
                {pending === status ? 'Сохраняем…' : current ? `${STATUS_LABEL[status]} ✓` : ACTION_LABEL[status]}
              </button>
            )
          })}
          {decided && pending === undefined && (
            <button type="button" className="btn btn-lg btn-ghost" onClick={() => setChanging(false)}>
              Отмена
            </button>
          )}
        </div>
      ) : (
        <div className="decision-done">
          <span>
            Решение: <strong>{STATUS_LABEL[event.status] ?? event.status}</strong>
          </span>
          <button type="button" className="btn btn-ghost" onClick={() => setChanging(true)}>
            Изменить решение
          </button>
        </div>
      )}
      {error && (
        <p className="form-error decision-error" role="alert">
          Решение не сохранено: {error}
        </p>
      )}
    </div>
  )
}
