import { getMetrics } from '../api/client.ts'
import type { Catalog } from '../api/useCatalog.ts'
import { fmt, fmtPct, ruleRates } from './model.ts'
import { Section, SourceNote } from './parts.tsx'
import { useAsync } from './useAsync.ts'

export function MetricsSection({ catalog }: { catalog: Catalog }) {
  const { result, reload } = useAsync((signal) => getMetrics(signal), [])
  const metrics = result.data
  const rules = Object.entries(metrics?.rules ?? {})
  const title = (t: string) => catalog.rules.find((r) => r.type === t)?.title ?? t
  const missing = catalog.rules.filter((r) => !rules.some(([t]) => t === r.type))

  return (
    <Section id="metrics" title="Метрики обнаружения" source="GET /api/metrics" state={result} onRetry={reload} what="метрики">
      {metrics &&
        (rules.length === 0 ? (
          <p className="feed-empty muted">Метрики ещё не посчитаны: reports/metrics.json пуст</p>
        ) : (
          <>
            <SourceNote>
              Посчитаны офлайн по событиям на тестовых видео{metrics.test_set ? <>, разметка <code>{metrics.test_set}</code></> : null}. Бэкенд
              детектора в файле не указан.
            </SourceNote>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Правило</th>
                    <th scope="col" className="num">Размечено нарушений</th>
                    <th scope="col" className="num">Тревог</th>
                    <th scope="col" className="num">tp</th>
                    <th scope="col" className="num">fp</th>
                    <th scope="col" className="num">fn</th>
                    <th scope="col" className="num">Precision</th>
                    <th scope="col" className="num">Recall</th>
                  </tr>
                </thead>
                <tbody>
                  {rules.map(([type, m]) => {
                    const r = ruleRates(m)
                    return (
                      <tr key={type} data-rule={type}>
                        <td>
                          {title(type)} <code className="muted">{type}</code>
                        </td>
                        <td className="num">{fmt(r.labeled)}</td>
                        <td className="num">{fmt(r.alarms)}</td>
                        <td className="num">{fmt(m.tp)}</td>
                        <td className="num">{fmt(m.fp)}</td>
                        <td className="num">{fmt(m.fn)}</td>
                        <td className="num">{r.precision === null ? '— (нет тревог)' : fmtPct(r.precision)}</td>
                        <td className="num">{r.recall === null ? '— (нет разметки)' : fmtPct(r.recall)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <p className="chart-note muted">
              Precision = tp / (tp + fp), recall = tp / (tp + fn). Всего размеченных нарушений в расчёте:{' '}
              {fmt(rules.reduce((sum, [, m]) => sum + m.tp + m.fn, 0))}.
            </p>
            {missing.length > 0 && (
              <p className="chart-note muted">Не посчитаны: {missing.map((r) => r.title).join(', ')}.</p>
            )}
          </>
        ))}
    </Section>
  )
}
