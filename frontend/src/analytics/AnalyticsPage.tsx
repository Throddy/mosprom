import { useCatalog } from '../api/useCatalog.ts'
import type { ServerStatus } from '../api/useServerStatus.ts'
import { EventsSection } from './EventsSection.tsx'
import { LiveSection } from './LiveSection.tsx'
import { MetricsSection } from './MetricsSection.tsx'
import { PerformanceSection } from './PerformanceSection.tsx'

const LINKS = [
  { id: 'events', title: 'События' },
  { id: 'metrics', title: 'Метрики' },
  { id: 'perf', title: 'ONNX и LinQ' },
  { id: 'live', title: 'Камеры сейчас' },
]

// Дашборд FE-6: каждый раздел берёт данные из своего API и загружается независимо
export function AnalyticsPage({ server }: { server: ServerStatus }) {
  const catalog = useCatalog()

  return (
    <div className="analytics">
      <div className="feed-bar">
        <div className="feed-heading">
          <h2>Аналитика</h2>
        </div>
        <nav className="an-toc" aria-label="Разделы аналитики">
          {LINKS.map((l) => (
            <button key={l.id} type="button" className="link-btn" onClick={() => document.getElementById(`an-${l.id}`)?.scrollIntoView({ behavior: 'smooth' })}>
              {l.title}
            </button>
          ))}
        </nav>
      </div>
      {catalog.error && (
        <p className="filters-error">Названия правил и камер не загружены ({catalog.error}), показаны идентификаторы.</p>
      )}
      <EventsSection catalog={catalog} server={server} />
      <MetricsSection catalog={catalog} />
      <PerformanceSection />
      <LiveSection catalog={catalog} />
    </div>
  )
}
