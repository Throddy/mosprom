import { useEffect, useState } from 'react'

// Status из CONTRACT.md, раздел 6
interface Status {
  detector: string
  backend: string
  cameras: { id: string; online: boolean; fps: number; latency_ms: number }[]
}

type Backend =
  | { state: 'loading' }
  | { state: 'online'; status: Status }
  | { state: 'offline'; error: string }

const SECTIONS = [
  { title: 'Лента тревог', task: 'FE-3' },
  { title: 'Журнал событий', task: 'FE-4' },
  { title: 'Камеры и зоны', task: 'FE-5' },
  { title: 'Дашборд и замеры LinQ', task: 'FE-6' },
]

export default function App() {
  const [backend, setBackend] = useState<Backend>({ state: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/status', { signal: controller.signal })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json() as Promise<Status>
      })
      .then((status) => setBackend({ state: 'online', status }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        setBackend({ state: 'offline', error: err instanceof Error ? err.message : String(err) })
      })
    return () => controller.abort()
  }, [])

  return (
    <div className="app">
      <header className="header">
        <h1>Мониторинг нарушений ТБ</h1>
        <p className="subtitle">Видеоаналитика на LinQ TPU</p>
      </header>

      <main className="content">
        <section className="card">
          <h2>Сервер</h2>
          <BackendInfo backend={backend} />
        </section>

        <section className="card">
          <h2>Разделы</h2>
          <ul className="sections">
            {SECTIONS.map((s) => (
              <li key={s.task}>
                <span>{s.title}</span>
                <span className="muted">{s.task}</span>
              </li>
            ))}
          </ul>
        </section>
      </main>
    </div>
  )
}

function BackendInfo({ backend }: { backend: Backend }) {
  if (backend.state === 'loading') {
    return <p className="muted">Проверка подключения…</p>
  }
  if (backend.state === 'offline') {
    return (
      <p>
        <span className="dot dot-off" /> Нет связи с <code>/api/status</code>: {backend.error}
      </p>
    )
  }
  const { status } = backend
  const online = status.cameras.filter((c) => c.online).length
  return (
    <dl className="facts">
      <dt>Подключение</dt>
      <dd>
        <span className="dot dot-on" /> есть
      </dd>
      <dt>Детектор</dt>
      <dd>{status.detector}</dd>
      <dt>Бэкенд детектора</dt>
      <dd>{status.backend}</dd>
      <dt>Камеры онлайн</dt>
      <dd>
        {online} из {status.cameras.length}
      </dd>
    </dl>
  )
}
