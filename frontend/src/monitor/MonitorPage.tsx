import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { isTestMode, knownStatus } from '../api/source.ts'
import type { Camera, EventView } from '../api/types.ts'
import { useCatalog } from '../api/useCatalog.ts'
import type { ServerStatus } from '../api/useServerStatus.ts'
import { SEVERITY_LABEL } from '../alerts/feed.ts'
import type { AlertFeed } from '../alerts/useAlertFeed.ts'
import { FramePreview } from '../components/LiveVideo.tsx'
import { navigate, routeHref } from '../router.ts'
import { FrameStill } from './FrameStill.tsx'
import { usePageVisible } from './usePageVisible.ts'

interface Props {
  params: URLSearchParams
  server: ServerStatus
  feed: AlertFeed
}

type Layout = '1' | '2' | '4' | 'all'

// Сервер отдаёт MJPEG по HTTP/1.1, а браузер держит не больше 6 соединений с одним адресом.
// Живых потоков не больше 4, чтобы запросы тревог и WebSocket не ждали в очереди;
// остальные выбранные камеры показываются кадром раз в 5 с
export const MAX_LIVE = 4
const MAX_TILES = 16
const LAYOUTS: { id: Layout; label: string }[] = [
  { id: '1', label: '1' },
  { id: '2', label: '2' },
  { id: '4', label: '4' },
  { id: 'all', label: 'Все' },
]
const PHONE = '(max-width: 640px)'

function useMedia(query: string): boolean {
  const [match, setMatch] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const mq = window.matchMedia(query)
    const update = () => setMatch(mq.matches)
    mq.addEventListener('change', update)
    return () => mq.removeEventListener('change', update)
  }, [query])
  return match
}

// Выбор камер и раскладка хранятся в адресе: ?cams=cam1,cam2&layout=4&focus=cam2
export function MonitorPage({ params, server, feed }: Props) {
  const catalog = useCatalog()
  const visible = usePageVisible()
  const phone = useMedia(PHONE)
  const testMode = isTestMode(server)
  const status = knownStatus(server)
  const boxRef = useRef<HTMLDivElement>(null)
  const [fullscreen, setFullscreen] = useState(false)
  // запасной полноэкранный режим для браузеров без Fullscreen API у элементов (iPhone Safari)
  const [pseudo, setPseudo] = useState(false)

  const cameras = catalog.cameras
  const camsParam = params.get('cams')
  const selected = useMemo(() => {
    if (camsParam === null) return cameras.slice(0, MAX_TILES).map((c) => c.id)
    const want = camsParam.split(',').filter(Boolean)
    return cameras.filter((c) => want.includes(c.id)).map((c) => c.id)
  }, [camsParam, cameras])
  const layoutParam = params.get('layout') as Layout | null
  const layout: Layout =
    layoutParam && LAYOUTS.some((l) => l.id === layoutParam)
      ? layoutParam
      : selected.length <= 1
        ? '1'
        : selected.length === 2
          ? '2'
          : selected.length <= 4
            ? '4'
            : 'all'
  const focus = selected.includes(params.get('focus') ?? '') ? params.get('focus')! : (selected[0] ?? null)
  // Адрес, откуда пришли (окно тревоги); только внутренние адреса приложения
  const backParam = params.get('back')
  const back = backParam && backParam.startsWith('#/') ? backParam : null
  // Камеры из адреса, которых нет в GET /api/cameras: удалены или ссылка устарела
  const missing = camsParam !== null && !catalog.loading && !catalog.error
    ? camsParam.split(',').filter((id) => id && !cameras.some((c) => c.id === id))
    : []

  const go = useCallback(
    (next: { cams?: string[]; layout?: Layout; focus?: string | null }) => {
      const p: Record<string, string> = {}
      const cams = next.cams ?? selected
      if (next.cams !== undefined || camsParam !== null) p.cams = cams.join(',')
      const lay = next.layout ?? layoutParam
      if (lay) p.layout = lay
      const f = next.focus === undefined ? focus : next.focus
      if (f && cams.includes(f)) p.focus = f
      if (back) p.back = back
      navigate(routeHref('monitor', p), true)
    },
    [selected, camsParam, layoutParam, focus, back],
  )

  // Камеры на экране: на телефоне одна выбранная, иначе по раскладке, начиная с выбранной
  const shown = useMemo(() => {
    if (phone || layout === '1') return focus ? [focus] : []
    const count = layout === 'all' ? MAX_TILES : Number(layout)
    const start = focus ? selected.indexOf(focus) : 0
    const ordered = [...selected.slice(start), ...selected.slice(0, start)]
    return ordered.slice(0, count)
  }, [phone, layout, focus, selected])

  // Новые тревоги по камерам из живой ленты
  const alertsByCamera = useMemo(() => {
    const map = new Map<string, EventView[]>()
    for (const e of Object.values(feed.events)) {
      if (e.status !== 'new') continue
      const list = map.get(e.camera_id) ?? []
      list.push(e)
      map.set(e.camera_id, list)
    }
    for (const list of map.values()) list.sort((a, b) => b.ts_confirm - a.ts_confirm)
    return map
  }, [feed.events])

  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === boxRef.current)
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])

  useEffect(() => {
    if (!pseudo) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setPseudo(false)
    document.body.classList.add('no-scroll')
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.classList.remove('no-scroll')
      window.removeEventListener('keydown', onKey)
    }
  }, [pseudo])

  const toggleFullscreen = () => {
    if (fullscreen) {
      void document.exitFullscreen()
      return
    }
    if (pseudo) {
      setPseudo(false)
      return
    }
    const el = boxRef.current
    if (el && typeof el.requestFullscreen === 'function' && document.fullscreenEnabled) {
      el.requestFullscreen().catch(() => setPseudo(true))
    } else {
      setPseudo(true)
    }
  }

  const toggleCamera = (id: string) => {
    if (phone) {
      go({ focus: id })
      return
    }
    const next = selected.includes(id) ? selected.filter((x) => x !== id) : cameras.filter((c) => c.id === id || selected.includes(c.id)).map((c) => c.id)
    go({ cams: next })
  }

  const step = (dir: 1 | -1) => {
    if (!focus || selected.length < 2) return
    const i = selected.indexOf(focus)
    go({ focus: selected[(i + dir + selected.length) % selected.length] })
  }

  const live = (id: string) => status?.cameras.find((c) => c.id === id)
  const big = fullscreen || pseudo

  return (
    <section className="page monitor" aria-labelledby="monitor-title">
      <div className="page-head">
        <div>
          <h2 id="monitor-title">Монитор камер</h2>
          <p>
            {phone
              ? 'Одна камера на экране. Нажмите на название, чтобы переключить.'
              : `Выбрано камер: ${selected.length}. Живых потоков одновременно: до ${MAX_LIVE}.`}
          </p>
        </div>
      </div>

      {back && (
        <p className="back-link">
          <a href={back}>‹ Вернуться к тревоге</a>
        </p>
      )}

      {missing.length > 0 && (
        <div className="notice notice-error" role="alert" data-missing={missing.join(',')}>
          <span>
            {missing.length === 1
              ? `Камера «${missing[0]}» не найдена: возможно, её удалили из настроек.`
              : `Камеры не найдены: ${missing.join(', ')}. Возможно, их удалили из настроек.`}{' '}
            Выберите другую камеру ниже.
          </span>
        </div>
      )}

      {catalog.error && (
        <div className="notice notice-error" role="alert">
          <span>Не удалось загрузить камеры: {catalog.error}</span>
          <button type="button" className="btn" onClick={catalog.reload}>
            Повторить
          </button>
        </div>
      )}

      {catalog.loading && cameras.length === 0 ? (
        <p className="empty">Загружаем камеры…</p>
      ) : cameras.length === 0 ? (
        !catalog.error && <p className="empty">Камеры не подключены</p>
      ) : (
        <>
          <div className="monitor-bar">
            <div className="monitor-cams" role="group" aria-label={phone ? 'Какую камеру показать' : 'Какие камеры показать'}>
              {cameras.map((c) => {
                const on = phone ? c.id === focus : selected.includes(c.id)
                const l = live(c.id)
                return (
                  <button key={c.id} type="button" className="cam-chip" aria-pressed={on} onClick={() => toggleCamera(c.id)} data-camera={c.id}>
                    <span className={`dot ${!l ? 'dot-wait' : l.online ? 'dot-on' : 'dot-off'}`} aria-hidden="true" />
                    {c.name}
                  </button>
                )
              })}
            </div>
            {!phone && (
              <div className="segmented" role="group" aria-label="Раскладка">
                {LAYOUTS.map((l) => (
                  <button
                    key={l.id}
                    type="button"
                    aria-pressed={layout === l.id}
                    aria-label={l.id === 'all' ? 'Все выбранные камеры' : `Камер на экране: ${l.label}`}
                    onClick={() => go({ layout: l.id })}
                  >
                    {l.label}
                  </button>
                ))}
              </div>
            )}
            <button type="button" className="btn" onClick={toggleFullscreen} disabled={shown.length === 0}>
              Во весь экран
            </button>
          </div>

          {shown.length === 0 ? (
            <div className="empty">
              <p className="empty-title">Камеры не выбраны</p>
              <p>Отметьте камеры кнопками выше.</p>
            </div>
          ) : (
            <div
              ref={boxRef}
              className={`monitor-box${pseudo ? ' monitor-pseudo' : ''}${big ? ' monitor-big' : ''}`}
              data-layout={phone ? 'phone' : layout}
            >
              {big && (
                <div className="monitor-full-bar">
                  <span>Монитор камер</span>
                  {selected.length > 1 && (phone || layout === '1') && (
                    <span className="monitor-step">
                      <button type="button" className="btn btn-sm" onClick={() => step(-1)} aria-label="Предыдущая камера">
                        ‹
                      </button>
                      <button type="button" className="btn btn-sm" onClick={() => step(1)} aria-label="Следующая камера">
                        ›
                      </button>
                    </span>
                  )}
                  <button type="button" className="btn btn-sm" onClick={toggleFullscreen}>
                    Выйти из полного экрана
                  </button>
                </div>
              )}
              <div className={`monitor-grid monitor-grid-${Math.min(shown.length, 16)}`}>
                {shown.map((id, i) => {
                  const camera = cameras.find((c) => c.id === id)
                  if (!camera) return null
                  return (
                    <MonitorTile
                      key={id}
                      camera={camera}
                      online={live(id)?.online}
                      alerts={alertsByCamera.get(id) ?? []}
                      liveStream={i < MAX_LIVE}
                      paused={!visible}
                      testMode={testMode}
                    />
                  )
                })}
              </div>
            </div>
          )}

          {!phone && selected.length > MAX_LIVE && layout === 'all' && (
            <p className="muted small">
              Камеры после четвёртой показаны кадром раз в 5 секунд: сервер передаёт видео по HTTP/1.1, и браузер держит не больше
              шести соединений с ним одновременно.
            </p>
          )}
        </>
      )}
    </section>
  )
}

interface TileProps {
  camera: Camera
  online: boolean | undefined
  alerts: EventView[]
  liveStream: boolean
  paused: boolean
  testMode: boolean
}

function MonitorTile({ camera, online, alerts, liveStream, paused }: TileProps) {
  const latest = alerts[0]
  // Выделение держится, пока у камеры есть тревоги со статусом new; решение оператора его снимает
  const attention = alerts.length > 0
  return (
    <article className={attention ? 'tile-cam tile-cam-attention' : 'tile-cam'} data-camera-id={camera.id} data-attention={attention || undefined}>
      <header className="tile-cam-head">
        <div className="tile-cam-title">
          <a className="tile-cam-name" href={routeHref('cameras', { id: camera.id })} title="Подробный просмотр камеры">
            {camera.name}
          </a>
          {attention && <span className="tile-cam-flag">Требует внимания</span>}
        </div>
        <span className={online === undefined ? 'state muted' : online ? 'state state-ok' : 'state state-bad'}>
          <span className={`dot ${online === undefined ? 'dot-wait' : online ? 'dot-on' : 'dot-off'}`} aria-hidden="true" />
          {online === undefined ? 'Нет данных' : online ? 'В сети' : 'Нет сигнала'}
        </span>
      </header>
      {/* Нажатие на видео открывает подробный просмотр; с клавиатуры — ссылка с названием камеры выше */}
      <div
        className="tile-cam-video"
        onClick={(e) => {
          if (!(e.target instanceof Element && e.target.closest('button'))) navigate(routeHref('cameras', { id: camera.id }))
        }}
      >
        {liveStream ? (
          <FramePreview cameraId={camera.id} cameraName={camera.name} paused={paused} />
        ) : (
          <FrameStill cameraId={camera.id} cameraName={camera.name} paused={paused} />
        )}
      </div>
      {latest ? (
        <a className="tile-cam-alerts" href={routeHref('alerts', { event: latest.id })}>
          <span className={`badge badge-${latest.severity}`}>{SEVERITY_LABEL[latest.severity] ?? latest.severity}</span>
          <span className="tile-cam-alert-text">
            {latest.title ?? latest.type}
            {alerts.length > 1 && <span className="muted"> и ещё {alerts.length - 1}</span>}
          </span>
          <span className="tile-cam-open">Посмотреть</span>
        </a>
      ) : (
        <p className="tile-cam-alerts tile-cam-quiet">Новых тревог нет</p>
      )}
    </article>
  )
}
