import { getStatus } from '../api/client.ts'
import type { Catalog } from '../api/useCatalog.ts'
import { fmt } from './model.ts'
import { Section, SourceNote } from './parts.tsx'
import { useAsync } from './useAsync.ts'

const REFRESH_MS = 5000

export function LiveSection({ catalog }: { catalog: Catalog }) {
  const { result, reload } = useAsync((signal) => getStatus(signal), [], REFRESH_MS)
  const status = result.data
  const test = status?.backend === 'fixtures'
  const name = (id: string) => catalog.cameras.find((c) => c.id === id)?.name ?? id

  return (
    <Section id="live" title="Камеры сейчас" source="GET /api/status, раз в 5 с" state={result} onRetry={reload} what="состояние камер">
      {status && (
        <>
          {test ? (
            <SourceNote kind="test">
              Тестовый режим сервера (backend = fixtures): кадры/с и задержка не измеряются, сервер подставляет постоянные значения.
            </SourceNote>
          ) : (
            <SourceNote>
              Детектор: {status.detector} ({status.backend}). Задержка — время от получения кадра до результата правил (CONTRACT.md,
              раздел 6).
            </SourceNote>
          )}
          {status.cameras.length === 0 ? (
            <p className="feed-empty muted">Камер нет</p>
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Камера</th>
                    <th scope="col">Состояние</th>
                    <th scope="col" className="num">Кадров/с</th>
                    <th scope="col" className="num">Задержка, мс</th>
                  </tr>
                </thead>
                <tbody>
                  {status.cameras.map((c) => (
                    <tr key={c.id} data-camera={c.id}>
                      <td>
                        {name(c.id)} <code className="muted">{c.id}</code>
                      </td>
                      <td>
                        <span className={`dot ${c.online ? 'dot-on' : 'dot-off'}`} /> {c.online ? 'в сети' : 'не в сети'}
                      </td>
                      <td className="num">{test ? <span className="muted">не измерено</span> : fmt(c.fps, 1)}</td>
                      <td className="num">{test ? <span className="muted">не измерено</span> : fmt(c.latency_ms, 1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Section>
  )
}
