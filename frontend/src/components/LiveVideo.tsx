import Hls from 'hls.js'
import { useEffect, useRef, useState } from 'react'

// H.264 из /hls/<id>/index.m3u8 (BE-19), при недоступности HLS — прежний MJPEG в <img>.
// Сервер кодирует один поток на камеру, поэтому канал на зрителя в 5–10 раз меньше MJPEG.
const NO_PLAYBACK_MS = 15000
const IMG_POLL_MS = 300
const PREVIEW_MS = 2000

interface Props {
  cameraId: string
  // MJPEG /api/cameras/{id}/stream: запасной вариант
  fallbackSrc: string
  className?: string
  alt: string
  // первый показанный кадр: timeupdate у <video>, naturalWidth у <img>
  onLive?: () => void
  onError?: () => void
}

type Mode = 'probe' | 'hls' | 'img'

export function hlsUrl(cameraId: string): string {
  return `/hls/${encodeURIComponent(cameraId)}/index.m3u8`
}

export function LiveVideo({ cameraId, fallbackSrc, className, alt, onLive, onError }: Props) {
  const [mode, setMode] = useState<Mode>('probe')
  const videoRef = useRef<HTMLVideoElement>(null)
  const imgRef = useRef<HTMLImageElement>(null)
  const liveRef = useRef(onLive)
  const errorRef = useRef(onError)
  liveRef.current = onLive
  errorRef.current = onError

  // Есть ли плейлист HLS у камеры
  useEffect(() => {
    const controller = new AbortController()
    setMode('probe')
    fetch(hlsUrl(cameraId), { method: 'HEAD', cache: 'no-store', signal: controller.signal })
      .then((res) => setMode(res.ok ? 'hls' : 'img'))
      .catch(() => {
        if (!controller.signal.aborted) setMode('img')
      })
    return () => controller.abort()
  }, [cameraId])

  // HLS: Safari и iOS играют m3u8 сами, остальные браузеры через hls.js
  useEffect(() => {
    if (mode !== 'hls') return
    const video = videoRef.current
    if (!video) return
    const url = hlsUrl(cameraId)
    let hls: Hls | null = null
    let played = false
    const fallback = () => setMode('img')
    const timer = window.setTimeout(() => {
      if (!played) fallback()
    }, NO_PLAYBACK_MS)
    const onTime = () => {
      if (!played && video.currentTime > 0) {
        played = true
        liveRef.current?.()
      }
    }
    video.addEventListener('timeupdate', onTime)
    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = url
    } else if (Hls.isSupported()) {
      hls = new Hls({ liveSyncDurationCount: 2, lowLatencyMode: false })
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (data.fatal) fallback()
      })
      hls.loadSource(url)
      hls.attachMedia(video)
    } else {
      fallback()
    }
    void video.play().catch(() => {
      // autoplay muted разрешён; отказ без звука — значит, ждём действия пользователя
    })
    return () => {
      window.clearTimeout(timer)
      video.removeEventListener('timeupdate', onTime)
      hls?.destroy()
      video.removeAttribute('src')
      video.load()
    }
  }, [mode, cameraId])

  // MJPEG: src задаётся и снимается здесь, пустой src закрывает соединение потока
  useEffect(() => {
    if (mode !== 'img') return
    const img = imgRef.current
    if (!img) return
    img.src = fallbackSrc
    const timer = window.setInterval(() => {
      if (img.naturalWidth > 0) {
        liveRef.current?.()
        window.clearInterval(timer)
      }
    }, IMG_POLL_MS)
    return () => {
      window.clearInterval(timer)
      img.removeAttribute('src')
    }
  }, [mode, fallbackSrc])

  if (mode === 'img') {
    return <img ref={imgRef} className={className} alt={alt} onError={() => errorRef.current?.()} />
  }
  return <video ref={videoRef} className={className} autoPlay muted playsInline aria-label={alt} />
}

// Превью камеры в сетке: кадр /api/cameras/{id}/frame раз в 2 с вместо потока
export function FramePreview({ cameraId, cameraName, paused }: { cameraId: string; cameraName: string; paused: boolean }) {
  const [tick, setTick] = useState(() => Date.now())
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (paused) return
    const timer = window.setInterval(() => setTick(Date.now()), PREVIEW_MS)
    return () => window.clearInterval(timer)
  }, [paused])

  // Лёгкое превью: ширина 480 px, JPEG 70 (BE-20)
  const src = `/api/cameras/${encodeURIComponent(cameraId)}/frame?w=480&t=${tick}`
  return (
    <div className="stream">
      <div className={`stream-frame ${loaded ? 'stream-live' : 'stream-connecting'}`} data-stream-state={loaded ? 'still' : 'connecting'}>
        {!paused && <img src={src} alt={`Кадр камеры: ${cameraName}`} onLoad={() => setLoaded(true)} />}
        {!loaded && (
          <div className="stream-overlay" role="status">
            <p>Загружаем кадр…</p>
          </div>
        )}
      </div>
    </div>
  )
}
