import { getBenchmarks } from '../api/client.ts'
import type { Benchmark } from '../api/types.ts'
import { ColumnChart } from './charts.tsx'
import { ChartBlock } from './EventsSection.tsx'
import {
  KIND_LABEL,
  benchKind,
  best,
  byKind,
  fmt,
} from './model.ts'
import { Section, SourceNote, StatTile } from './parts.tsx'
import { useAsync } from './useAsync.ts'

const dateFmt = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })

export function PerformanceSection() {
  const { result, reload } = useAsync((signal) => getBenchmarks(signal), [])
  const list = result.data

  return (
    <Section id="perf" title="Скорость работы на LinQ" source="GET /api/benchmarks" state={result} onRetry={reload} what="замеры">
      {list && (list.length === 0 ? <p className="empty">Замеров скорости пока нет</p> : <Perf list={list} />)}
    </Section>
  )
}

function Perf({ list }: { list: Benchmark[] }) {
  const onnx = byKind(list, 'onnx')
  const service = byKind(list, 'linq-service')
  const accel = byKind(list, 'linq-accelerator')
  const bestOnnx = best(onnx)
  const bestService = best(service)
  const accelRec = best(accel)

  return (
    <>
      <div className="kpi-row">
        {bestOnnx && (
          <StatTile
            label="На обычном процессоре (ONNX)"
            value={fmt(bestOnnx.fps, 2)}
            unit="кадра/с"
            note={`Измерено: ${bestOnnx.device}, ${bestOnnx.streams} пот. суммарно`}
          />
        )}
        {bestService && (
          <StatTile
            label="LinQ через облачный стенд"
            value={fmt(bestService.fps, 2)}
            unit="кадра/с"
            note={`Измерено вместе с сетью и очередью стенда, ${bestService.streams} пот. суммарно`}
          />
        )}
        {accelRec && (
          <StatTile
            label="Ускоритель LinQ, один кадр"
            value={fmt(accelRec.latency_ms.infer, 1)}
            unit="мс"
            note={`Только работа ускорителя, без сети и подготовки кадра. По этому времени ${fmt(accelRec.fps, 2)} кадра/с, это расчёт`}
          />
        )}
      </div>

      <SourceNote>
        Время ускорителя и путь кадра через облачный стенд измерены отдельно. Скорость тревоги на стенде определяет полный путь кадра.
      </SourceNote>

      <details className="more">
        <summary>Все замеры и графики</summary>
      <div className="chart-grid">
        {onnx.length > 0 && (
          <ChartBlock title={`${KIND_LABEL.onnx}: пропускная способность по числу потоков`} unit="кадров/с суммарно">
            <ColumnChart
              label="ONNX, кадров в секунду по числу потоков"
              unit="кадров/с"
              digits={2}
              height={120}
              columns={onnx.map((b) => ({ key: String(b.streams), label: `${b.streams} пот.`, value: b.fps, tick: `${b.streams}` }))}
            />
            <p className="chart-note muted">Подпись под колонкой — число потоков. {onnx[0].device}</p>
          </ChartBlock>
        )}
        {service.length > 0 && (
          <ChartBlock title={`${KIND_LABEL['linq-service']}: пропускная способность по числу потоков`} unit="кадров/с суммарно">
            <ColumnChart
              label="LinQ через облачный стенд, кадров в секунду по числу потоков"
              unit="кадров/с"
              digits={2}
              height={120}
              columns={service.map((b) => ({ key: String(b.streams), label: `${b.streams} пот.`, value: b.fps, tick: `${b.streams}` }))}
            />
            <p className="chart-note muted">Подпись под колонкой — число потоков. Своя шкала: значения на порядок меньше ONNX.</p>
          </ChartBlock>
        )}
      </div>

      <h4>Таблица замеров</h4>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Вид</th>
              <th scope="col">Устройство</th>
              <th scope="col">Модель</th>
              <th scope="col">Точность</th>
              <th scope="col" className="num">Потоков</th>
              <th scope="col" className="num">Кадров/с, суммарно</th>
              <th scope="col" className="num">pre, мс</th>
              <th scope="col" className="num">infer, мс</th>
              <th scope="col" className="num">post, мс</th>
              <th scope="col" className="num">total, мс</th>
              <th scope="col">Замер</th>
            </tr>
          </thead>
          <tbody>
            {list.map((b, i) => (
              <tr key={i} data-kind={benchKind(b)}>
                <td>{KIND_LABEL[benchKind(b)]}</td>
                <td className="device-cell">{b.device}</td>
                <td>
                  <code>{b.model}</code>
                </td>
                <td>{b.precision}</td>
                <td className="num">{b.streams}</td>
                <td className="num">{fmt(b.fps, 3)}</td>
                <td className="num">{fmt(b.latency_ms.pre, 1)}</td>
                <td className="num">{fmt(b.latency_ms.infer, 1)}</td>
                <td className="num">{fmt(b.latency_ms.post, 1)}</td>
                <td className="num">{fmt(b.latency_ms.total, 1)}</td>
                <td>{Number.isNaN(Date.parse(b.measured_at)) ? b.measured_at : dateFmt.format(new Date(b.measured_at))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="chart-note muted">
        Кадров/с — суммарно по всем потокам замера (CONTRACT.md, раздел 8). total — время на кадр по пропускной способности, при нескольких
        потоках кадры обрабатываются параллельно, поэтому задержка одного кадра больше total.
      </p>
      </details>
    </>
  )
}
