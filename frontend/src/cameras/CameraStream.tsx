import { useEffect, useRef, useState } from 'react'
import { streamUrl } from '../api/client.ts'
import { LiveVideo } from '../components/LiveVideo.tsx'

type StreamState = 'connecting' | 'live' | 'error' | 'timeout'

const FIRST_FRAME_MS = 10000

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

// Видео камеры через LiveVideo: H.264 из /hls/<id>/index.m3u8, при недоступности — MJPEG из
// GET /api/cameras/{id}/stream в <img>. Первый кадр: timeupdate у <video>, naturalWidth у <img>
export function CameraStream({ cameraId, cameraName, testMode, paused = false, note = true }: Props) {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<StreamState>('connecting')
  const attemptRef = useRef(0)

  useEffect(() => {
    if (paused) return
    const current = attempt
    attemptRef.current = current
    setState('connecting')
    const timer = window.setTimeout(() => {
      if (attemptRef.current === current) setState((s) => (s === 'connecting' ? 'timeout' : s))
    }, FIRST_FRAME_MS)
    return () => {
      window.clearTimeout(timer)
      attemptRef.current = -1
    }
  }, [attempt, cameraId, paused])

  const onLive = () => {
    if (attemptRef.current === attempt) setState((s) => (s === 'connecting' || s === 'timeout' ? 'live' : s))
  }
  const onError = () => {
    if (attemptRef.current === attempt) setState('error')
  }

  const shown = paused ? 'paused' : state

  return (
    <div className="stream">
      <div className={`stream-frame stream-${shown}`} data-stream-state={shown}>
        {!paused && (
          <LiveVideo
            key={`${cameraId}-${attempt}`}
            cameraId={cameraId}
            fallbackSrc={streamUrl(cameraId)}
            alt={`Видео с камеры: ${cameraName}`}
            onLive={onLive}
            onError={onError}
          />
        )}
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
