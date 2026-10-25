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
  // true: поток не открывается (вкладка скрыта), соединение с сервером освобождается
  paused?: boolean
  // подпись под видео; в сетке монитора не нужна
  note?: boolean
}

// MJPEG из GET /api/cameras/{id}/stream в <img>. Первый кадр определяется по naturalWidth:
// событие load для multipart-ответа браузеры вызывают не одинаково
export function CameraStream({ cameraId, cameraName, testMode, paused = false, note = true }: Props) {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<StreamState>('connecting')
  const imgRef = useRef<HTMLImageElement>(null)
  const attemptRef = useRef(0)

  useEffect(() => {
    if (paused) return
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
  }, [attempt, cameraId, paused])

  const onError = () => {
    if (attemptRef.current === attempt) setState('error')
  }

  const shown = paused ? 'paused' : state

  return (
    <div className="stream">
      <div className={`stream-frame stream-${shown}`} data-stream-state={shown}>
        <img key={`${cameraId}-${attempt}`} ref={imgRef} alt={`Видео с камеры: ${cameraName}`} onError={onError} />
        {shown !== 'live' && (
          <div className="stream-overlay" role="status">
            {shown === 'paused' && <p>Видео на паузе, пока вкладка скрыта</p>}
            {shown === 'connecting' && <p>Подключаемся к камере…</p>}
            {shown === 'error' && <p>Видео с камеры недоступно</p>}
            {shown === 'timeout' && <p>Камера не передаёт изображение {FIRST_FRAME_MS / 1000} секунд</p>}
            {(shown === 'error' || shown === 'timeout') && (
              <button type="button" className="btn" onClick={() => setAttempt((a) => a + 1)}>
                Повторить
              </button>
            )}
          </div>
        )}
      </div>
      {note && (
        <p className="stream-note muted">
          {testMode
            ? 'Тестовый режим сервера: кадр синтетический, нейросеть не работает.'
            : 'Люди и техника обведены рамками, опасные зоны отмечены красным контуром.'}
        </p>
      )}
    </div>
  )
}
