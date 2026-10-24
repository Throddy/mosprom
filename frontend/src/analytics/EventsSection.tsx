import { useMemo, useState, type ReactNode } from 'react'
import { getStats } from '../api/client.ts'
import type { Catalog } from '../api/useCatalog.ts'
import type { ServerStatus } from '../api/useServerStatus.ts'
import { SEVERITY_LABEL, STATUS_LABEL } from '../alerts/feed.ts'
import { routeHref } from '../router.ts'
import { BarList, ColumnChart, type Bar } from './charts.tsx'
import { PERIODS, entries, fmt, fmtPct, periodRange, share, type Period } from './model.ts'
import { Section, SourceNote, StatTile } from './parts.tsx'
import { useAsync } from './useAsync.ts'

interface Props {
  catalog: Catalog
  server: ServerStatus
}

const dayFmt = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit' })

export function EventsSection({ catalog, server }: Props) {
  const [period, setPeriod] = useState<Period>('all')
  // Начало периода фиксируется при выборе, чтобы журнал по ссылке показал те же события
  const r = useMemo(() => periodRange(period, Date.now() / 1000), [period])
  const { result, reload } = useAsync((signal) => getStats(signal, r), [r])
  const stats = result.data

  const typeTitle = (t: string) => catalog.rules.find((x) => x.type === t)?.title ?? t
  const cameraName = (id: string) => catalog.cameras.find((c) => c.id === id)?.name ?? id
  const journal = (filter: Record<string, string>) =>
    routeHref('journal', r.from !== undefined ? { ...filter, from: String(r.from) } : filter)

  const backend = server.state === 'online' ? server.status.backend : null

  return (
    <Section
      id="events"
      title="События"
      source="GET /api/stats"
      actions={
        <div className="segmented" role="group" aria-label="Период">
          {PERIODS.map((p) => (
            <button key={p.id} type="button" aria-pressed={period === p.id} onClick={() => setPeriod(p.id)}>
              {p.label}
            </button>
          ))}
        </div>
      }
      state={result}
      onRetry={reload}
      what="статистику событий"
    >
      {backend === 'fixtures' && (
        <SourceNote kind="test">
          В базе тестовые события сервера (PIPELINE=0, /api/status: backend = fixtures). Это не результат нейросети.
        </SourceNote>
      )}
      {backend && backend !== 'fixtures' && (
        <SourceNote>
          Счёт по всем событиям базы. Детектор сервера сейчас: {server.state === 'online' ? server.status.detector : ''} ({backend}).
        </SourceNote>
      )}

      {stats &&
        (stats.total === 0 ? (
          <p className="feed-empty muted">За выбранный период событий нет</p>
        ) : (
          <>
            <div className="kpi-row">
              <StatTile label="Всего событий" value={fmt(stats.total)} />
              <StatTile
                label="Необработанные"
                value={fmt(stats.by_status.new ?? 0)}
                note={`${fmtPct(share(stats.by_status.new ?? 0, stats.total))} от всех`}
              />
              <StatTile
                label="Критичные"
                value={fmt(stats.by_severity.critical ?? 0)}
                note={`${fmtPct(share(stats.by_severity.critical ?? 0, stats.total))} от всех`}
              />
              <FalseShare stats={stats.by_status} />
            </div>

            <div className="chart-grid">
              <ChartBlock title="По типам нарушений" unit="событий">
                <BarList
                  label="События по типам"
                  unit="событий"
                  bars={entries(stats.by_type).map<Bar>((e) => ({ key: e.key, label: typeTitle(e.key), value: e.value, href: journal({ type: e.key }) }))}
                />
              </ChartBlock>
              <ChartBlock title="По камерам" unit="событий">
                <BarList
                  label="События по камерам"
                  unit="событий"
                  bars={entries(stats.by_camera).map<Bar>((e) => ({ key: e.key, label: cameraName(e.key), value: e.value, href: journal({ camera_id: e.key }) }))}
                />
              </ChartBlock>
              <ChartBlock title="По статусам" unit="событий">
                <BarList
                  label="События по статусам"
                  unit="событий"
                  bars={entries(stats.by_status).map<Bar>((e) => ({
                    key: e.key,
                    label: STATUS_LABEL[e.key as keyof typeof STATUS_LABEL] ?? e.key,
                    value: e.value,
                    href: journal({ status: e.key }),
                  }))}
                />
              </ChartBlock>
              <ChartBlock title="По критичности" unit="событий">
                <BarList
                  label="События по критичности"
                  unit="событий"
                  bars={entries(stats.by_severity).map<Bar>((e) => ({ key: e.key, label: SEVERITY_LABEL[e.key] ?? e.key, value: e.value }))}
                />
              </ChartBlock>
            </div>

            <ChartBlock title="По часу тревоги" unit="событий" note="Час ts_confirm по местному времени сервера, сумма за период">
              <ColumnChart
                label="События по часу тревоги"
                unit="событий"
                columns={stats.by_hour.map((v, h) => ({ key: String(h), label: `${h}:00–${h}:59`, value: v, tick: h % 3 === 0 ? String(h) : '' }))}
              />
            </ChartBlock>

            {Object.keys(stats.by_day).length > 1 && (
              <ChartBlock title="По дням" unit="событий">
                <ColumnChart
                  label="События по дням"
                  unit="событий"
                  height={120}
                  columns={Object.entries(stats.by_day).map(([day, v]) => {
                    const label = dayFmt.format(new Date(`${day}T12:00:00`))
                    return { key: day, label, value: v, tick: label }
                  })}
                />
              </ChartBlock>
            )}
          </>
        ))}
    </Section>
  )
}

// Доля «ложное» среди событий, по которым оператор принял решение
function FalseShare({ stats }: { stats: Record<string, number> }) {
  const decided = (stats.confirmed ?? 0) + (stats.false ?? 0) + (stats.forwarded ?? 0)
  const falseCount = stats.false ?? 0
  return (
    <StatTile
      label="Ложные среди обработанных"
      value={decided > 0 ? fmtPct(share(falseCount, decided)) : '—'}
      note={decided > 0 ? `${fmt(falseCount)} из ${fmt(decided)} решений оператора` : 'оператор ещё не принимал решений'}
    />
  )
}

export function ChartBlock({ title, unit, note, children }: { title: string; unit: string; note?: string; children: ReactNode }) {
  return (
    <div className="chart-block">
      <h4>
        {title}
        <span className="muted chart-unit">, {unit}</span>
      </h4>
      {note && <p className="chart-note muted">{note}</p>}
      {children}
    </div>
  )
}
