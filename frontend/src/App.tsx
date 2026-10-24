import { useEffect, useMemo } from 'react'
import { AlertFeed } from './alerts/AlertFeed.tsx'
import { useAlertFeed } from './alerts/useAlertFeed.ts'
import { useServerStatus, type ServerStatus } from './api/useServerStatus.ts'
import { CamerasPage } from './cameras/CamerasPage.tsx'
import { JournalPage } from './journal/JournalPage.tsx'
import { routeHref, useRoute, type Page } from './router.ts'

// Значения Status.backend из CONTRACT.md, раздел 4
const DETECTOR_BACKENDS: Record<string, string> = {
  onnx: 'ONNX Runtime, CPU',
  linq: 'LinQ TPU',
}

const NAV: { page: Page; title: string }[] = [
  { page: 'alerts', title: 'Лента тревог' },
  { page: 'journal', title: 'Журнал событий' },
  { page: 'cameras', title: 'Камеры' },
]

const BASE_TITLE = document.title

export default function App() {
  const server = useServerStatus()
  // Лента и её WebSocket живут на уровне приложения: тревоги приходят на любой странице
  const feed = useAlertFeed()
  const route = useRoute()

  const unhandled = useMemo(() => Object.values(feed.events).filter((e) => e.status === 'new').length, [feed.events])

  useEffect(() => {
    document.title = unhandled ? `(${unhandled}) ${BASE_TITLE}` : BASE_TITLE
  }, [unhandled])

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <h1>Мониторинг нарушений ТБ</h1>
          <p className="subtitle">Видеоаналитика на LinQ TPU</p>
        </div>
        <ServerInfo server={server} />
      </header>

      <nav className="nav" aria-label="Разделы">
        {NAV.map((item) => (
          <a
            key={item.page}
            href={routeHref(item.page)}
            aria-current={route.page === item.page ? 'page' : undefined}
          >
            {item.title}
            {item.page === 'alerts' && unhandled > 0 && (
              <span className="nav-count" aria-label={`необработанных: ${unhandled}`}>
                {unhandled}
              </span>
            )}
          </a>
        ))}
      </nav>

      <main>
        {route.page === 'alerts' && <AlertFeed feed={feed} />}
        {route.page === 'journal' && <JournalPage params={route.params} subscribe={feed.subscribe} />}
        {route.page === 'cameras' && <CamerasPage params={route.params} server={server} />}
      </main>
    </div>
  )
}

function ServerInfo({ server }: { server: ServerStatus }) {
  if (server.state === 'loading') {
    return <p className="server muted">Проверка подключения…</p>
  }
  if (server.state === 'offline') {
    return (
      <div className="server">
        <p>
          <span className="dot dot-off" /> Нет связи с <code>/api/status</code>: {server.error}
        </p>
        {server.last && (
          <p className="muted">
            Последний известный детектор:{' '}
            <DetectorSource detector={server.last.detector} backend={server.last.backend} />
          </p>
        )}
      </div>
    )
  }
  const { status } = server
  const online = status.cameras.filter((c) => c.online).length
  return (
    <dl className="server facts">
      <dt>Сервер</dt>
      <dd>
        <span className="dot dot-on" /> есть связь
      </dd>
      <dt>Детектор</dt>
      <dd>
        <DetectorSource detector={status.detector} backend={status.backend} />
      </dd>
      <dt>Камеры онлайн</dt>
      <dd>
        {online} из {status.cameras.length}
      </dd>
    </dl>
  )
}

// Источник берётся только из /api/status и описывает текущий детектор сервера
function DetectorSource({ detector, backend }: { detector: string; backend: string }) {
  const label = DETECTOR_BACKENDS[backend]
  if (label) {
    return (
      <>
        {detector} <span className="muted">· {label}</span>
      </>
    )
  }
  if (backend === 'fixtures') {
    return (
      <span className="source-test" title="GET /api/status: backend = fixtures">
        тестовые данные сервера, не результат нейросети
      </span>
    )
  }
  return (
    <>
      {detector} <span className="muted">· backend «{backend}»</span>
    </>
  )
}
