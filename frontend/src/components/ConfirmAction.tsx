import { useState } from 'react'

interface Props {
  // подпись кнопки, например «Удалить зону»
  label: string
  // вопрос подтверждения
  question: string
  confirmLabel?: string
  disabled?: boolean
  onConfirm: () => void
}

// Опасное действие в два шага: тихая кнопка, затем вопрос с «Удалить» и «Отмена»
export function ConfirmAction({ label, question, confirmLabel = 'Удалить', disabled = false, onConfirm }: Props) {
  const [asking, setAsking] = useState(false)

  if (!asking) {
    return (
      <button type="button" className="btn btn-danger-quiet" disabled={disabled} onClick={() => setAsking(true)}>
        {label}
      </button>
    )
  }
  return (
    <div className="confirm" role="alertdialog" aria-label={label}>
      <p>{question}</p>
      <div className="confirm-actions">
        <button
          type="button"
          className="btn btn-danger"
          onClick={() => {
            setAsking(false)
            onConfirm()
          }}
        >
          {confirmLabel}
        </button>
        <button type="button" className="btn btn-ghost" onClick={() => setAsking(false)} autoFocus>
          Отмена
        </button>
      </div>
    </div>
  )
}
