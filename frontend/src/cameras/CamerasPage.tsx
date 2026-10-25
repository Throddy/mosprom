import { isTestMode } from '../api/source.ts'
import type { Camera, RuleSpec, Status } from '../api/types.ts'
import { useCatalog } from '../api/useCatalog.ts'
import type { ServerStatus } from '../api/useServerStatus.ts'
import { routeHref } from '../router.ts'
import { CameraEditor } from './CameraEditor.tsx'
import { CameraStream } from './CameraStream.tsx'
import { paramLabel } from './ruleText.ts'

interface Props {
  params: URLSearchParams
  server: ServerStatus
}

type Live = Status['cameras'][number]
type Tab = 'video' | 'zones'

export function CamerasPage({ params, server }: Props) {
  const catalog = useCatalog()
  const status = server.state === 'online' ? server.status : null
  const live = (id: string) => status?.cameras.find((c) => c.id === id)
  const requested = params.get('id')
  const camera = catalog.cameras.find((c) => c.id === requested) ?? (requested ? undefined : catalog.cameras[0])
  const tab: Tab = params.get('tab') === 'zones' ? 'zones' : 'video'
  const href = (id: string, t: Tab) => routeHref('cameras', t === 'zones' ? { id, tab: t } : { id })

  return (
    <section className="page cameras" aria-labelledby="cameras-title">
      <div className="page-head">
        <div>
          <h2 id="cameras-title">Камеры и зоны</h2>
          {!catalog.loading && !catalog.error && <p className="muted">Всего камер: {catalog.cameras.length}</p>}
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
        <p className="empty">Загружаем камеры…</p>
      ) : catalog.cameras.length === 0 ? (
        !catalog.error && <p className="empty">Камеры не подключены</p>
      ) : (
        <div className="cameras-layout">
          <ul className="camera-list" aria-label="Список камер">
            {catalog.cameras.map((c) => (
              <li key={c.id}>
                <a href={href(c.id, tab)} aria-current={c.id === camera?.id ? 'true' : undefined}>
                  <span className="camera-name">{c.name}</span>
                  <OnlineState live={live(c.id)} />
                </a>
              </li>
            ))}
          </ul>

          {camera ? (
            <article className="camera-view" data-camera-id={camera.id}>
              <div className="camera-head">
                <h3>{camera.name}</h3>
                <a href={routeHref('journal', { camera_id: camera.id })}>Тревоги камеры в журнале</a>
              </div>
              <nav className="segmented camera-tabs" aria-label="Раздел камеры">
                <a href={href(camera.id, 'video')} aria-current={tab === 'video' ? 'page' : undefined}>
                  Видео
                </a>
                <a href={href(camera.id, 'zones')} aria-current={tab === 'zones' ? 'page' : undefined}>
                  Зоны и правила
                </a>
              </nav>
              {tab === 'zones' ? (
                <CameraEditor
                  key={camera.id}
                  camera={camera}
                  specs={catalog.rules}
                  specsError={catalog.error}
                  onSaved={catalog.reload}
                />
              ) : (
                <CameraView
                  key={camera.id}
                  camera={camera}
                  live={live(camera.id)}
                  rules={catalog.rules}
                  testMode={isTestMode(server)}
                  zonesHref={href(camera.id, 'zones')}
                />
              )}
            </article>
          ) : (
            <p className="empty">Камера «{requested}» не найдена</p>
          )}
        </div>
      )}
    </section>
  )
}

function OnlineState({ live }: { live: Live | undefined }) {
  if (!live) {
    return (
      <span className="state muted">
        <span className="dot dot-wait" aria-hidden="true" /> Нет данных
      </span>
    )
  }
  return (
    <span className={live.online ? 'state state-ok' : 'state state-bad'}>
      <span className={`dot ${live.online ? 'dot-on' : 'dot-off'}`} aria-hidden="true" /> {live.online ? 'В сети' : 'Нет сигнала'}
    </span>
  )
}

interface ViewProps {
  camera: Camera
  live: Live | undefined
  rules: RuleSpec[]
  testMode: boolean
  zonesHref: string
}

function CameraView({ camera, live, rules, testMode, zonesHref }: ViewProps) {
  const zoneName = (id: string | null) => (id ? (camera.zones.find((z) => z.id === id)?.name ?? id) : null)

  return (
    <>
      <CameraStream cameraId={camera.id} cameraName={camera.name} testMode={testMode} />

      <dl className="facts">
        <dt>Состояние</dt>
        <dd>
          <OnlineState live={live} />
        </dd>
        {live && !testMode && (
          <>
            <dt>Обработка</dt>
            <dd>
              {live.fps} кадр/с, задержка {live.latency_ms} мс
            </dd>
          </>
        )}
      </dl>

      <h4>Что проверяет камера</h4>
      {camera.rules.length === 0 ? (
        <p className="muted">Проверки не настроены</p>
      ) : (
        <ul className="rule-list">
          {camera.rules.map((r, i) => {
            const spec = rules.find((s) => s.type === r.type)
            return (
              <li key={`${r.type}-${i}`} className={r.enabled ? undefined : 'muted'}>
                <strong>{spec?.title ?? r.type}</strong>
                <span>
                  {r.enabled ? 'включено' : 'выключено'}
                  {' · '}
                  {r.zone ? `зона «${zoneName(r.zone)}»` : 'весь кадр'}
                  {' · '}
                  {r.schedule ? `с ${r.schedule[0]} до ${r.schedule[1]}` : 'круглосуточно'}
                </span>
              </li>
            )
          })}
        </ul>
      )}

      <h4>Опасные зоны</h4>
      {camera.zones.length === 0 ? (
        <p className="muted">Зоны не размечены</p>
      ) : (
        <ul className="rule-list">
          {camera.zones.map((z) => (
            <li key={z.id}>
              <strong>{z.name}</strong>
              <span className="muted">точек контура: {z.polygon.length}</span>
            </li>
          ))}
        </ul>
      )}
      <p>
        <a href={zonesHref}>Посмотреть зоны на кадре</a>
      </p>

      <details className="more">
        <summary>Технические данные</summary>
        <dl className="facts facts-small">
          <dt>id</dt>
          <dd>
            <code>{camera.id}</code>
          </dd>
          <dt>Источник</dt>
          <dd>
            <code>{camera.source}</code>
          </dd>
          <dt>Частота анализа</dt>
          <dd>{camera.fps} кадр/с</dd>
          {camera.rules.map((r, i) => {
            const spec = rules.find((s) => s.type === r.type)
            const params = Object.entries(r.params ?? {})
            if (params.length === 0) return null
            return (
              <div className="facts-row" key={`${r.type}-${i}`}>
                <dt>{spec?.title ?? r.type}</dt>
                <dd>
                  {params.map(([k, v]) => {
                    const unit = spec?.params.find((p) => p.name === k)?.unit
                    return (
                      <span key={k} className="param">
                        {paramLabel(k)}: {String(v)}
                        {unit ? ` ${unit}` : ''}
                      </span>
                    )
                  })}
                </dd>
              </div>
            )
          })}
        </dl>
      </details>
    </>
  )
}
