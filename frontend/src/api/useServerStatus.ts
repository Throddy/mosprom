import { useEffect, useState } from 'react'
import { getStatus } from './client.ts'
import type { Status } from './types.ts'

const REFRESH_MS = 15000
const RETRY_MS = 3000

export type ServerStatus =
  | { state: 'loading' }
  | { state: 'online'; status: Status }
  | { state: 'offline'; error: string; last: Status | null }

// GET /api/status с периодическим обновлением: детектор может смениться без перезагрузки страницы.
// После ошибки запрос повторяется чаще, чтобы шапка не отставала от восстановленного соединения.
export function useServerStatus(): ServerStatus {
  const [server, setServer] = useState<ServerStatus>({ state: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    let timer: number | undefined
    let last: Status | null = null

    const load = () => {
      getStatus(controller.signal)
        .then((status) => {
          last = status
          setServer({ state: 'online', status })
          timer = window.setTimeout(load, REFRESH_MS)
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return
          setServer({ state: 'offline', error: err instanceof Error ? err.message : String(err), last })
          timer = window.setTimeout(load, RETRY_MS)
        })
    }
    load()

    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [])

  return server
}
