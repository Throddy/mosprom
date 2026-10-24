import { AlertFeed } from './alerts/AlertFeed.tsx'
import { useServerStatus, type ServerStatus } from './api/useServerStatus.ts'

// Значения Status.backend из CONTRACT.md, раздел 4
const DETECTOR_BACKENDS: Record<string, string> = {
  onnx: 'ONNX Runtime, CPU',
  linq: 'LinQ TPU',
}

export default function App() {
  const server = useServerStatus()

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <h1>Мониторинг нарушений ТБ</h1>
          <p className="subtitle">Видеоаналитика на LinQ TPU</p>
        </div>
        <ServerInfo server={server} />
      </header>

      <main>
        <AlertFeed />
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
