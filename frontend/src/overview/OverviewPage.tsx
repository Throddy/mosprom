import { useMemo } from 'react'
import { useReadOnly } from '../api/readOnly.ts'
import { dataSource, knownStatus } from '../api/source.ts'
import { useCatalog } from '../api/useCatalog.ts'
import type { ServerStatus } from '../api/useServerStatus.ts'
import { SEVERITY_LABEL, STATUS_LABEL, sortFeed } from '../alerts/feed.ts'
import { formatAgo, formatTs } from '../alerts/format.ts'
import type { AlertFeed } from '../alerts/useAlertFeed.ts'
import { useNow } from '../alerts/useNow.ts'
import { routeHref } from '../router.ts'

interface Props {
  feed: AlertFeed
  server: ServerStatus
}

const LIST_LIMIT = 5

// Табло: состояние безопасности, камеры, тревоги, ждущие решения, и следующее действие
export function OverviewPage({ feed, server }: Props) {
  const catalog = useCatalog()
  const now = useNow()
  const readOnly = useReadOnly() !== null
  const status = knownStatus(server)
  const source = status ? dataSource(status) : null

  const sorted = useMemo(() => sortFeed(feed.events), [feed.events])
  const unhandled = useMemo(() => sorted.filter((e) => e.status === 'new'), [sorted])
  // Всего новых на сервере: загруженные в ленту и те, что за пределами её окна
  const newTotal = unhandled.length + feed.hiddenNew
  const critical = unhandled.filter((e) => e.severity === 'critical').length
  // Без новых тревог показываются последние по времени, с решением оператора
  const recent = useMemo(
    () => (unhandled.length > 0 ? unhandled : [...sorted].sort((a, b) => b.ts_confirm - a.ts_confirm)).slice(0, LIST_LIMIT),
    [unhandled, sorted],
  )

  const cameras = status?.cameras ?? []
  const online = cameras.filter((c) => c.online).length
  const cameraName = (id: string) => catalog.cameras.find((c) => c.id === id)?.name ?? id
  const newByCamera = (id: string) => unhandled.filter((e) => e.camera_id === id).length

  const state = server.state === 'offline' ? 'offline' : !feed.loaded ? 'loading' : newTotal > 0 ? 'danger' : 'calm'

  return (
    <section className="page overview" aria-labelledby="overview-title">
      <h2 id="overview-title" className="sr-only">
        Обзор
      </h2>
      {/* Расшифровка названия: первые буквы слов складываются в «СОКОЛ» */}
      <p className="tagline">
        <b>С</b>истема <b>О</b>бнаружения и <b>К</b>онтроля <b>О</b>пасностей на <b>L</b>inQ
      </p>

      <div className={`status-strip status-${state}`} role="status" data-state={state}>
        <div className="status-main">
          <p className="status-label">Безопасность</p>
          <p className="status-value">
            {state === 'danger' && `Новых тревог: ${newTotal}`}
            {state === 'calm' && 'Новых тревог нет'}
            {state === 'offline' && 'Нет связи с сервером'}
            {state === 'loading' && 'Загружаем данные…'}
          </p>
          <p className="status-note">
            {state === 'danger' &&
              (critical > 0
                ? `${feed.hiddenNew > 0 ? 'Критичных среди последних' : 'Из них критичных'}: ${critical}. ${readOnly ? 'Посмотрите кадры тревог.' : 'Посмотрите кадр и примите решение.'}`
                : readOnly
                  ? 'Посмотрите кадры тревог.'
                  : 'Посмотрите кадр и примите решение.')}
            {state === 'calm' && 'Система следит за камерами. Новая тревога появится здесь и всплывёт в углу экрана.'}
            {state === 'offline' && 'Новые тревоги не приходят. Подключение восстановится автоматически.'}
          </p>
        </div>

        <dl className="status-facts">
          <div>
            <dt>Камеры в сети</dt>
            <dd className={status && online < cameras.length ? 'text-danger' : undefined}>
              {status ? `${online} из ${cameras.length}` : 'нет данных'}
            </dd>
          </div>
          <div>
            <dt>Откуда тревоги</dt>
            <dd className={source?.test ? 'text-warn' : undefined} title={source?.detail}>
              {source ? source.label : 'нет данных'}
            </dd>
          </div>
        </dl>

        <div className="status-action">
          {state === 'danger' ? (
            <a className="btn btn-lg btn-primary" href={routeHref('alerts')}>
              Разобрать тревоги
            </a>
          ) : (
            <a className="btn btn-lg btn-primary" href={routeHref('monitor')}>
              Открыть монитор
            </a>
          )}
        </div>
      </div>

      <div className="overview-grid">
        <section className="panel" aria-labelledby="ov-alerts">
          <header className="panel-head">
            <h3 id="ov-alerts">{unhandled.length > 0 ? 'Требуют решения' : 'Последние тревоги'}</h3>
            <a href={routeHref('alerts', unhandled.length > 0 ? undefined : { show: 'all' })}>Все тревоги</a>
          </header>
          {recent.length === 0 ? (
            <p className="panel-empty">{feed.loaded ? 'Тревог пока не было.' : 'Загружаем…'}</p>
          ) : (
            <ul className="mini-list">
              {recent.map((e) => {
                const ago = formatAgo(e.ts_confirm, now)
                return (
                  <li key={e.id}>
                    <a
                      className={`mini-alert sev-${e.severity}`}
                      href={routeHref('alerts', { ...(unhandled.length ? {} : { show: 'all' }), event: e.id })}
                    >
                      <span className="mini-snap">
                        {e.snapshot_url ? <img src={e.snapshot_url} alt="" loading="lazy" /> : <span className="snap-empty">Нет кадра</span>}
                      </span>
                      <span className="mini-text">
                        <span className="mini-title">{e.title ?? e.type}</span>
                        <span className="muted">
                          {e.camera_name ?? e.camera_id} · {ago ?? formatTs(e.ts_confirm)}
                        </span>
                      </span>
                      <span className="mini-tags">
                        <span className={`badge badge-${e.severity}`}>{SEVERITY_LABEL[e.severity] ?? e.severity}</span>
                        {e.status !== 'new' && <span className={`chip chip-${e.status}`}>{STATUS_LABEL[e.status] ?? e.status}</span>}
                      </span>
                    </a>
                  </li>
                )
              })}
            </ul>
          )}
        </section>

        <div className="overview-side">
          <section className="panel panel-quiet" aria-labelledby="ov-cams">
            <header className="panel-head">
              <h3 id="ov-cams">Камеры</h3>
              <a href={routeHref('monitor')}>Монитор</a>
            </header>
            {cameras.length === 0 ? (
              <p className="panel-empty">{status ? 'Камеры не подключены.' : 'Нет данных от сервера.'}</p>
            ) : (
              <ul className="cam-rows">
                {cameras.map((c) => {
                  const n = newByCamera(c.id)
                  return (
                    <li key={c.id}>
                      <a className="cam-row" href={routeHref('cameras', { id: c.id })}>
                        <span className="cam-row-name">{cameraName(c.id)}</span>
                        <span className={c.online ? 'state state-ok' : 'state state-bad'}>
                          <span className={`dot ${c.online ? 'dot-on' : 'dot-off'}`} aria-hidden="true" />
                          {c.online ? 'В сети' : 'Нет сигнала'}
                        </span>
                        <span className={n > 0 ? 'cam-row-alerts text-danger' : 'cam-row-alerts muted'}>
                          {n > 0 ? `новых тревог: ${n}` : 'тревог нет'}
                        </span>
                      </a>
                    </li>
                  )
                })}
              </ul>
            )}
          </section>

          <details className="panel panel-quiet help">
            <summary>Как работать с тревогой</summary>
            <ol className="steps">
              <li>Новая тревога всплывает в углу экрана и появляется в разделе «Тревоги», самые опасные сверху.</li>
              <li>Нажмите на тревогу: откроется кадр с выделенным человеком, камера, зона и время.</li>
              <li>Выберите «Подтвердить», «Ложная тревога» или «Передать мастеру». Решение попадёт в журнал.</li>
            </ol>
          </details>
        </div>
      </div>
    </section>
  )
}
