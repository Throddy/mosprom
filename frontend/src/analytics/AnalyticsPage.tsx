import { useCatalog } from '../api/useCatalog.ts'
import type { ServerStatus } from '../api/useServerStatus.ts'
import { EventsSection } from './EventsSection.tsx'
import { LiveSection } from './LiveSection.tsx'
import { MetricsSection } from './MetricsSection.tsx'
import { PerformanceSection } from './PerformanceSection.tsx'

const LINKS = [
  { id: 'events', title: 'Тревоги' },
  { id: 'metrics', title: 'Точность' },
  { id: 'perf', title: 'Скорость LinQ' },
  { id: 'live', title: 'Камеры сейчас' },
]

// Дашборд FE-6: каждый раздел берёт данные из своего API и загружается независимо
export function AnalyticsPage({ server }: { server: ServerStatus }) {
  const catalog = useCatalog()

  return (
    <div className="page analytics">
      <div className="page-head">
        <div>
          <h2>Аналитика</h2>
          <p className="muted">Сколько было тревог, насколько точно система их находит и как быстро работает на LinQ.</p>
        </div>
      </div>
      <nav className="chips an-toc" aria-label="Разделы аналитики">
        {LINKS.map((l) => (
          <button
            key={l.id}
            type="button"
            className="chip-btn"
            onClick={() => document.getElementById(`section-${l.id}`)?.scrollIntoView({ behavior: 'smooth' })}
          >
            {l.title}
          </button>
        ))}
      </nav>
      {catalog.error && <p className="form-error">Названия правил и камер не загружены ({catalog.error}), показаны идентификаторы.</p>}
      <EventsSection catalog={catalog} server={server} />
      <MetricsSection catalog={catalog} />
      <PerformanceSection />
      <LiveSection catalog={catalog} />
    </div>
  )
}
