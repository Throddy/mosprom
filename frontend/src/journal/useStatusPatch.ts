import { useCallback, useState } from 'react'
import { patchEvent, userMessage } from '../api/client.ts'
import { noteForbidden } from '../api/readOnly.ts'
import type { EventStatus, EventView } from '../api/types.ts'

function without<T>(rec: Record<string, T>, key: string): Record<string, T> {
  if (!(key in rec)) return rec
  const next = { ...rec }
  delete next[key]
  return next
}

// PATCH статуса вне ленты: результат отдаётся в onSaved, лента FE-3 получит его через event_update.
// При ошибке, в том числе 403 демо-стенда, onSaved не вызывается
export function useStatusPatch(onSaved: (view: EventView) => void) {
  const [pending, setPending] = useState<Record<string, EventStatus>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})

  const setStatus = useCallback(
    (event: EventView, status: EventStatus) => {
      setPending((p) => ({ ...p, [event.id]: status }))
      setErrors((e) => without(e, event.id))
      patchEvent(event.id, status, event.comment)
        .then(onSaved)
        .catch((err: unknown) => {
          noteForbidden(err)
          setErrors((e) => ({ ...e, [event.id]: userMessage(err) }))
        })
        .finally(() => setPending((p) => without(p, event.id)))
    },
    [onSaved],
  )

  return { pending, errors, setStatus }
}
