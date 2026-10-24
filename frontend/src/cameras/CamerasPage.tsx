import type { Camera, RuleSpec, Status } from '../api/types.ts'
import { useCatalog } from '../api/useCatalog.ts'
import type { ServerStatus } from '../api/useServerStatus.ts'
import { routeHref } from '../router.ts'
import { CameraStream } from './CameraStream.tsx'

interface Props {
  params: URLSearchParams
  server: ServerStatus
}

type Live = Status['cameras'][number]

export function CamerasPage({ params, server }: Props) {
  const catalog = useCatalog()
  const status = server.state === 'online' ? server.status : null
  const live = (id: string) => status?.cameras.find((c) => c.id === id)
  const requested = params.get('id')
  const camera = catalog.cameras.find((c) => c.id === requested) ?? (requested ? undefined : catalog.cameras[0])

  return (
    <section className="cameras" aria-labelledby="cameras-title">
      <div className="feed-bar">
        <div className="feed-heading">
          <h2 id="cameras-title">Камеры</h2>
          {!catalog.loading && !catalog.error && <span className="muted">всего: {catalog.cameras.length}</span>}
        </div>
      </div>

      {catalog.error && (
        <div className="notice notice-error" role="alert">
          <span>Не удалось загрузить камеры: {catalog.error}</span>
          <button type="button" className="btn" onClick={catalog.reload}>
            Повторить
          </button>
        </div>
      )}

      {catalog.loading && catalog.cameras.length === 0 ? (
        <p className="feed-empty muted">Загрузка камер…</p>
      ) : catalog.cameras.length === 0 ? (
        !catalog.error && <p className="feed-empty muted">Камер нет: GET /api/cameras вернул пустой список</p>
      ) : (
        <div className="cameras-layout">
          <ul className="camera-list" aria-label="Список камер">
            {catalog.cameras.map((c) => {
              const l = live(c.id)
              return (
                <li key={c.id}>
                  <a href={routeHref('cameras', { id: c.id })} aria-current={c.id === camera?.id ? 'true' : undefined}>
                    <span className="camera-name">
                      <OnlineDot live={l} />
                      {c.name}
                    </span>
                    <span className="muted">
                      {c.id} · зон: {c.zones.length} · правил: {c.rules.length}
                    </span>
                  </a>
                </li>
              )
            })}
          </ul>

          {camera ? (
            <CameraView
              key={camera.id}
              camera={camera}
              live={live(camera.id)}
              rules={catalog.rules}
              testMode={status?.backend === 'fixtures'}
            />
          ) : (
            <p className="feed-empty muted">
              Камера <code>{requested}</code> не найдена в GET /api/cameras
            </p>
          )}
        </div>
      )}
    </section>
  )
}

function OnlineDot({ live }: { live: Live | undefined }) {
  if (!live) return <span className="dot dot-wait" title="нет данных /api/status" />
  return <span className={`dot ${live.online ? 'dot-on' : 'dot-off'}`} title={live.online ? 'в сети' : 'не в сети'} />
}

function CameraView({ camera, live, rules, testMode }: { camera: Camera; live: Live | undefined; rules: RuleSpec[]; testMode: boolean }) {
  const zoneName = (id: string | null) => (id ? (camera.zones.find((z) => z.id === id)?.name ?? id) : null)

  return (
    <article className="camera-view" data-camera-id={camera.id}>
      <div className="camera-head">
        <h3>{camera.name}</h3>
        <a href={routeHref('journal', { camera_id: camera.id })}>События камеры в журнале</a>
      </div>

      <CameraStream cameraId={camera.id} cameraName={camera.name} testMode={testMode} />

      <dl className="details-meta">
        <dt>id</dt>
        <dd>
          <code>{camera.id}</code>
        </dd>
        <dt>Источник</dt>
        <dd>
          <code>{camera.source}</code>
        </dd>
        <dt>Частота обработки</dt>
        <dd>{camera.fps} кадр/с</dd>
        <dt>Состояние</dt>
        <dd>
          {live ? (
            <>
              <OnlineDot live={live} /> {live.online ? 'в сети' : 'не в сети'} · {live.fps} кадр/с · задержка{' '}
              {live.latency_ms} мс
            </>
          ) : (
            <span className="muted">нет данных /api/status</span>
          )}
        </dd>
      </dl>

      <h4>Зоны</h4>
      {camera.zones.length === 0 ? (
        <p className="muted">Зон нет</p>
      ) : (
        <ul className="plain-list">
          {camera.zones.map((z) => (
            <li key={z.id}>
              {z.name} <code className="muted">{z.id}</code> <span className="muted">· точек: {z.polygon.length}</span>
            </li>
          ))}
        </ul>
      )}

      <h4>Правила</h4>
      {camera.rules.length === 0 ? (
        <p className="muted">Правил нет</p>
      ) : (
        <ul className="plain-list">
          {camera.rules.map((r, i) => {
            const spec = rules.find((s) => s.type === r.type)
            const params = Object.entries(r.params ?? {})
            return (
              <li key={`${r.type}-${i}`} className={r.enabled ? undefined : 'muted'}>
                {spec?.title ?? r.type} <code className="muted">{r.type}</code>
                {!spec && <span className="muted"> · нет в /api/rules</span>}
                {!r.enabled && ' · выключено'}
                {r.zone && ` · зона: ${zoneName(r.zone)}`}
                {r.schedule && ` · ${r.schedule[0]}–${r.schedule[1]}`}
                {params.length > 0 && (
                  <span className="muted"> · {params.map(([k, v]) => `${k}=${String(v)}`).join(', ')}</span>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </article>
  )
}
