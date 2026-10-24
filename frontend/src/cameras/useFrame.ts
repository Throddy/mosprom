import { useCallback, useEffect, useState } from 'react'
import { ApiError, errorText, getFrame } from '../api/client.ts'

export type FrameState =
  | { state: 'loading' }
  | { state: 'ready'; url: string }
  // 503: сервер ещё не получил кадр с камеры
  | { state: 'empty'; detail: string }
  | { state: 'error'; message: string }

// Кадр для разметки: GET /api/cameras/{id}/frame как blob, чтобы различать 503 и прочие ошибки
export function useFrame(cameraId: string): { frame: FrameState; reload: () => void } {
  const [attempt, setAttempt] = useState(0)
  const [frame, setFrame] = useState<FrameState>({ state: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    let url: string | null = null
    setFrame({ state: 'loading' })
    getFrame(cameraId, controller.signal)
      .then((blob) => {
        url = URL.createObjectURL(blob)
        setFrame({ state: 'ready', url })
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        if (err instanceof ApiError && err.status === 503) {
          setFrame({ state: 'empty', detail: err.detail ?? 'кадра ещё нет' })
        } else {
          setFrame({ state: 'error', message: errorText(err) })
        }
      })
    return () => {
      controller.abort()
      if (url) URL.revokeObjectURL(url)
    }
  }, [cameraId, attempt])

  const reload = useCallback(() => setAttempt((a) => a + 1), [])
  return { frame, reload }
}
