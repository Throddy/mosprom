import { useEffect, useRef, useState } from 'react'
import { streamUrl } from '../api/client.ts'

type StreamState = 'connecting' | 'live' | 'error' | 'timeout'

const FIRST_FRAME_MS = 10000
const POLL_MS = 300

interface Props {
  cameraId: string
  cameraName: string
  // backend = fixtures в /api/status: сервер отдаёт синтетические кадры
  testMode: boolean
}

// MJPEG из GET /api/cameras/{id}/stream в <img>. Первый кадр определяется по naturalWidth:
// событие load для multipart-ответа браузеры вызывают не одинаково
export function CameraStream({ cameraId, cameraName, testMode }: Props) {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<StreamState>('connecting')
  const imgRef = useRef<HTMLImageElement>(null)
  const attemptRef = useRef(0)

  useEffect(() => {
    const current = attempt
    attemptRef.current = current
    setState('connecting')
    const img = imgRef.current
    // src задаётся здесь, а не в разметке: очистка ниже его снимает, и повторный запуск
    // эффекта (StrictMode, смена камеры, «Повторить») должен открыть поток заново
    if (img) img.src = streamUrl(cameraId)
    const started = Date.now()
    const timer = window.setInterval(() => {
      if (attemptRef.current !== current) return
      if (img && img.naturalWidth > 0) {
        setState((s) => (s === 'connecting' ? 'live' : s))
        window.clearInterval(timer)
      } else if (Date.now() - started > FIRST_FRAME_MS) {
        setState((s) => (s === 'connecting' ? 'timeout' : s))
        window.clearInterval(timer)
      }
    }, POLL_MS)
    return () => {
      window.clearInterval(timer)
      attemptRef.current = -1
      // Пустой src закрывает соединение потока при уходе со страницы
      if (img) img.removeAttribute('src')
    }
  }, [attempt, cameraId])

  const onError = () => {
    if (attemptRef.current === attempt) setState('error')
  }

  return (
    <div className="stream">
      <div className={`stream-frame stream-${state}`}>
        <img
          key={`${cameraId}-${attempt}`}
          ref={imgRef}
          alt={`Видеопоток: ${cameraName}`}
          onError={onError}
        />
        {state !== 'live' && (
          <div className="stream-overlay" role="status">
            {state === 'connecting' && <p>Подключение к видеопотоку…</p>}
            {state === 'error' && (
              <p>
                Видеопоток недоступен: <code>{streamUrl(cameraId)}</code> вернул ошибку.
              </p>
            )}
            {state === 'timeout' && (
              <p>
                Видеопоток не передаёт кадры {FIRST_FRAME_MS / 1000} с. Источник камеры не открыт или кадров ещё нет.
              </p>
            )}
            {(state === 'error' || state === 'timeout') && (
              <button type="button" className="btn" onClick={() => setAttempt((a) => a + 1)}>
                Повторить
              </button>
            )}
          </div>
        )}
      </div>
      <p className="stream-note muted">
        {testMode
          ? 'Сервер в тестовом режиме (/api/status: backend = fixtures): кадр синтетический, детекций нет.'
          : 'Кадры с треками и зонами от сервера.'}
      </p>
    </div>
  )
}
