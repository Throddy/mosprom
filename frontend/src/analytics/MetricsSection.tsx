import { getMetrics } from '../api/client.ts'
import type { Catalog } from '../api/useCatalog.ts'
import { fmt, fmtPct, ruleRates } from './model.ts'
import { Section, SourceNote } from './parts.tsx'
import { useAsync } from './useAsync.ts'

// Метрики из reports/metrics.json: tp — найдено, fn — пропущено, fp — ложные тревоги
export function MetricsSection({ catalog }: { catalog: Catalog }) {
  const { result, reload } = useAsync((signal) => getMetrics(signal), [])
  const metrics = result.data
  // Бег на стенде не показывается: правило распознаёт бег только в части сцен (BE-20)
  const rules = Object.entries(metrics?.rules ?? {}).filter(([type]) => type !== 'running')
  const title = (t: string) => catalog.rules.find((r) => r.type === t)?.title ?? t
  const missing = catalog.rules.filter((r) => r.type !== 'running' && !rules.some(([t]) => t === r.type))

  return (
    <Section id="metrics" title="Точность распознавания" source="GET /api/metrics" state={result} onRetry={reload} what="метрики">
      {metrics &&
        (rules.length === 0 ? (
          <p className="empty">Проверка точности ещё не проводилась</p>
        ) : (
          <>
            <SourceNote>
              Проверка на заранее размеченных видео, которых система не видела при настройке
              {metrics.test_set ? (
                <>
                  {' '}
                  (разметка <code>{metrics.test_set}</code>)
                </>
              ) : null}
              .
            </SourceNote>
            <ul className="metric-cards">
              {rules.map(([type, m]) => {
                const r = ruleRates(m)
                return (
                  <li key={type} className="metric-card" data-rule={type}>
                    <p className="metric-title">{title(type)}</p>
                    <p className="metric-main">
                      Найдено <strong>{fmt(m.tp)}</strong> из <strong>{fmt(r.labeled)}</strong>
                      {r.labeled === 0 && <span className="muted"> (нарушений в видео не было)</span>}
                    </p>
                    <dl className="facts facts-small">
                      <dt>Пропущено</dt>
                      <dd>{fmt(m.fn)}</dd>
                      <dt>Ложных тревог</dt>
                      <dd>{fmt(m.fp)}</dd>
                      <dt>Точность</dt>
                      <dd>{r.precision === null ? 'тревог не было' : fmtPct(r.precision)}</dd>
                      <dt>Полнота</dt>
                      <dd>{r.recall === null ? 'нет разметки' : fmtPct(r.recall)}</dd>
                    </dl>
                  </li>
                )
              })}
            </ul>
            <p className="chart-note muted">
              Точность: какая доля тревог оказалась настоящими нарушениями. Полнота: какую долю нарушений система нашла. Всего размеченных
              нарушений: {fmt(rules.reduce((sum, [, m]) => sum + m.tp + m.fn, 0))}.
            </p>
            {missing.length > 0 && <p className="chart-note muted">Не проверялись: {missing.map((r) => r.title).join(', ')}.</p>}
          </>
        ))}
    </Section>
  )
}
