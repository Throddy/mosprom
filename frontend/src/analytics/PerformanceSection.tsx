import { useState } from 'react'
import { getBenchmarks } from '../api/client.ts'
import type { Benchmark } from '../api/types.ts'
import { ColumnChart } from './charts.tsx'
import { ChartBlock } from './EventsSection.tsx'
import {
  KIND_LABEL,
  benchKind,
  best,
  boardsNeeded,
  byKind,
  camerasPerBoard,
  contractLinqRecord,
  fmt,
} from './model.ts'
import { Section, SourceNote, StatTile } from './parts.tsx'
import { useAsync } from './useAsync.ts'

const dateFmt = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })

function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10
  const m100 = n % 100
  if (m10 === 1 && m100 !== 11) return one
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few
  return many
}

const cameras = (n: number) => `${fmt(n)} ${plural(n, 'камера', 'камеры', 'камер')}`
const boards = (n: number) => `${fmt(n)} ${plural(n, 'плата', 'платы', 'плат')}`

export function PerformanceSection() {
  const { result, reload } = useAsync((signal) => getBenchmarks(signal), [])
  const list = result.data

  return (
    <Section id="perf" title="Производительность: ONNX и LinQ TPU" source="GET /api/benchmarks" state={result} onRetry={reload} what="замеры">
      {list && (list.length === 0 ? <p className="feed-empty muted">Замеров нет: reports/benchmarks.json пуст</p> : <Perf list={list} />)}
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
            label="ONNX Runtime, наибольшая пропускная способность"
            value={fmt(bestOnnx.fps, 2)}
            unit="кадра/с"
            note={`${bestOnnx.device}, ${bestOnnx.precision}, ${bestOnnx.streams} пот., суммарно. Измерено`}
          />
        )}
        {bestService && (
          <StatTile
            label="LinQ TPU через облачный стенд"
            value={fmt(bestService.fps, 2)}
            unit="кадра/с"
            note={`${bestService.precision}, ${bestService.streams} пот., суммарно, с сетью и очередью сервиса. Измерено`}
          />
        )}
        {accelRec && (
          <StatTile
            label="LinQ TPU, только время ускорителя"
            value={fmt(accelRec.latency_ms.infer, 1)}
            unit="мс на кадр"
            note={`Без пре- и постобработки, сети и очереди. Пропускная способность по этому времени ${fmt(accelRec.fps, 2)} кадра/с: расчёт`}
          />
        )}
      </div>

      <SourceNote>
        Время ускорителя и полный путь кадра через облачный стенд — разные величины. Задержку тревоги для LinQ определяет полный путь.
      </SourceNote>

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

      <Calculator list={list} />

      <h4>Все замеры</h4>
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
    </>
  )
}

const PRESETS = [2, 3, 5, 10]

// Калькулятор по CONTRACT.md, раздел 8: камер на плату = floor(fps / fps_камеры), fps — наибольший среди записей linq
function Calculator({ list }: { list: Benchmark[] }) {
  const [camFps, setCamFps] = useState('10')
  const [count, setCount] = useState('')
  const contract = contractLinqRecord(list)
  const service = best(byKind(list, 'linq-service'))
  const fpsNum = Number(camFps.replace(',', '.'))
  const valid = Number.isFinite(fpsNum) && fpsNum > 0 && fpsNum <= 30
  const countNum = Number(count)
  const countValid = count.trim() !== '' && Number.isInteger(countNum) && countNum > 0

  if (!contract) {
    return <p className="feed-empty muted">Калькулятор недоступен: в замерах нет записей backend = linq</p>
  }

  const perBoard = valid ? camerasPerBoard(contract.fps, fpsNum) : 0
  const perBoardService = valid && service ? camerasPerBoard(service.fps, fpsNum) : null

  return (
    <div className="calc" data-section="calc">
      <h4>Камер на одну плату LinQ</h4>
      <div className="calc-inputs">
        <label>
          <span>Частота анализа камеры, кадров/с</span>
          <input type="number" min={0.1} max={30} step="any" value={camFps} onChange={(e) => setCamFps(e.target.value)} />
        </label>
        <div className="calc-presets" role="group" aria-label="Частота анализа">
          {PRESETS.map((p) => (
            <button key={p} type="button" className="btn btn-small" aria-pressed={Number(camFps) === p} onClick={() => setCamFps(String(p))}>
              {p}
            </button>
          ))}
        </div>
        <label>
          <span>Камер на объекте</span>
          <input type="number" min={1} step={1} placeholder="например, 50" value={count} onChange={(e) => setCount(e.target.value)} />
        </label>
      </div>

      {!valid ? (
        <p className="form-error">Частота камеры: число больше 0 и не больше 30</p>
      ) : (
        <div className="calc-results">
          <div className="calc-result" data-calc="contract">
            <div className="stat-label">По формуле контракта, {KIND_LABEL[benchKind(contract)]}</div>
            <div className="stat-value">{cameras(perBoard)}</div>
            <div className="stat-note muted">
              floor({fmt(contract.fps, 3)} / {fmt(fpsNum, 2)}) = {perBoard}. Расчёт, не замер
              {benchKind(contract) === 'linq-accelerator' ? ': без сети, очереди и обработки кадра' : ''}.
            </div>
            {countValid && (
              <div className="calc-boards">
                {perBoard > 0
                  ? `Для ${cameras(countNum)}: ${boards(boardsNeeded(countNum, perBoard)!)}, ceil(${countNum} / ${perBoard})`
                  : 'Одна плата не обработает и одну камеру с такой частотой'}
              </div>
            )}
          </div>
          {service && perBoardService !== null && benchKind(contract) !== 'linq-service' && (
            <div className="calc-result" data-calc="service">
              <div className="stat-label">Через облачный стенд, по измеренным {fmt(service.fps, 2)} кадра/с</div>
              <div className="stat-value">{cameras(perBoardService)}</div>
              <div className="stat-note muted">
                floor({fmt(service.fps, 3)} / {fmt(fpsNum, 2)}) = {perBoardService}.{' '}
                {perBoardService === 0 ? 'Стенд не тянет одну камеру с такой частотой.' : ''}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
