import { useEffect, useState } from 'react'
import { getFrame } from '../api/client.ts'

const REFRESH_MS = 5000

// Кадр камеры через GET /api/cameras/{id}/frame раз в 5 с: для камер сверх лимита живых потоков.
// Короткий запрос не держит соединение, как MJPEG
export function FrameStill({ cameraId, cameraName, paused }: { cameraId: string; cameraName: string; paused: boolean }) {
  const [url, setUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (paused) return
    const controller = new AbortController()
    let timer: number | undefined
    let current: string | null = null
    const load = () => {
      getFrame(cameraId, controller.signal)
        .then((blob) => {
          const next = URL.createObjectURL(blob)
          if (current) URL.revokeObjectURL(current)
          current = next
          setUrl(next)
          setFailed(false)
        })
        .catch(() => {
          if (!controller.signal.aborted) setFailed(true)
        })
        .finally(() => {
          if (!controller.signal.aborted) timer = window.setTimeout(load, REFRESH_MS)
        })
    }
    load()
    return () => {
      controller.abort()
      window.clearTimeout(timer)
      if (current) URL.revokeObjectURL(current)
    }
  }, [cameraId, paused])

  return (
    <div className="stream">
      <div className={`stream-frame ${url && !failed ? 'stream-live' : 'stream-connecting'}`} data-stream-state={url && !failed ? 'still' : 'connecting'}>
        {url && <img src={url} alt={`Кадр камеры: ${cameraName}`} />}
        {(!url || failed) && (
          <div className="stream-overlay" role="status">
            <p>{failed ? 'Кадр с камеры недоступен' : 'Загружаем кадр…'}</p>
          </div>
        )}
        <span className="still-badge">Кадр раз в 5 с</span>
      </div>
    </div>
  )
}
