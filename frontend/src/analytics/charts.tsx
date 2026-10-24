import { fmt } from './model.ts'

export interface Bar {
  key: string
  label: string
  value: number
  // ссылка на события в журнале
  href?: string
}

// Горизонтальные столбики с подписью значения у каждого: один ряд, один цвет
export function BarList({ bars, unit, digits = 0, label }: { bars: Bar[]; unit: string; digits?: number; label: string }) {
  const max = Math.max(0, ...bars.map((b) => b.value))
  return (
    <ul className="barlist" aria-label={label}>
      {bars.map((b) => {
        const text = `${b.label}: ${fmt(b.value, digits)} ${unit}`
        return (
          <li key={b.key} title={text}>
            {b.href ? (
              <a className="barlist-label" href={b.href}>
                {b.label}
              </a>
            ) : (
              <span className="barlist-label">{b.label}</span>
            )}
            <span className="barlist-track">
              {b.value > 0 && <span className="barlist-bar" style={{ width: `${(b.value / max) * 100}%` }} />}
            </span>
            <span className="barlist-value">{fmt(b.value, digits)}</span>
          </li>
        )
      })}
    </ul>
  )
}

export interface Column {
  key: string
  label: string
  value: number
  // подпись под колонкой; пустая строка — без подписи
  tick: string
}

// Колонки с осью от нуля: максимум подписан на оси, значение каждой колонки — во всплывающей подсказке и в таблице
export function ColumnChart({ columns, unit, digits = 0, label, height = 160 }: { columns: Column[]; unit: string; digits?: number; label: string; height?: number }) {
  const max = Math.max(0, ...columns.map((c) => c.value))
  return (
    <figure className="colchart" aria-label={label}>
      <div className="colchart-plot" style={{ height }}>
        <span className="colchart-max">
          {fmt(max, digits)} {unit}
        </span>
        <div className="colchart-cols">
          {columns.map((c) => (
            <div key={c.key} className="colchart-col" title={`${c.label}: ${fmt(c.value, digits)} ${unit}`}>
              {c.value > 0 && max > 0 && <span className="colchart-bar" style={{ height: `${(c.value / max) * 100}%` }} />}
            </div>
          ))}
        </div>
      </div>
      <div className="colchart-ticks" aria-hidden="true">
        {columns.map((c) => (
          <span key={c.key}>{c.tick}</span>
        ))}
      </div>
    </figure>
  )
}
