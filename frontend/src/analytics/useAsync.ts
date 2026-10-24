import { useCallback, useEffect, useState } from 'react'
import { errorText } from '../api/client.ts'

export type Async<T> =
  | { state: 'loading'; data: T | null }
  | { state: 'ok'; data: T; at: number }
  | { state: 'error'; data: T | null; error: string }

// Загрузка одного источника: прежние данные остаются на экране во время повторного запроса.
// refreshMs — периодическое обновление (для /api/status)
export function useAsync<T>(load: (signal: AbortSignal) => Promise<T>, deps: unknown[], refreshMs?: number) {
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<Async<T>>({ state: 'loading', data: null })

  useEffect(() => {
    const controller = new AbortController()
    let timer: number | undefined
    const run = () => {
      setResult((r) => (r.state === 'ok' && refreshMs ? r : { state: 'loading', data: r.data }))
      load(controller.signal)
        .then((data) => setResult({ state: 'ok', data, at: Date.now() }))
        .catch((err: unknown) => {
          if (controller.signal.aborted) return
          setResult((r) => ({ state: 'error', data: r.data, error: errorText(err) }))
        })
        .finally(() => {
          if (refreshMs && !controller.signal.aborted) timer = window.setTimeout(run, refreshMs)
        })
    }
    run()
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
    // load меняется вместе с deps
  }, [...deps, attempt, refreshMs])

  const reload = useCallback(() => setAttempt((a) => a + 1), [])
  return { result, reload }
}
