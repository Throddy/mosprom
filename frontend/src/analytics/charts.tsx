import { useState } from 'react'
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

// Колонки с осью от нуля: максимум подписан на оси. Значение колонки видно в строке под графиком
// при наведении, касании или фокусе с клавиатуры, а также во всплывающей подсказке
export function ColumnChart({ columns, unit, digits = 0, label, height = 160 }: { columns: Column[]; unit: string; digits?: number; label: string; height?: number }) {
  const [active, setActive] = useState<string | null>(null)
  const max = Math.max(0, ...columns.map((c) => c.value))
  const current = columns.find((c) => c.key === active)
  return (
    <figure className="colchart" aria-label={label}>
      <div className="colchart-plot" style={{ height }} onMouseLeave={() => setActive(null)}>
        <span className="colchart-max">
          {fmt(max, digits)} {unit}
        </span>
        <div className="colchart-cols">
          {columns.map((c) => {
            const text = `${c.label}: ${fmt(c.value, digits)} ${unit}`
            return (
              <button
                key={c.key}
                type="button"
                className={c.key === active ? 'colchart-col colchart-col-active' : 'colchart-col'}
                title={text}
                aria-label={text}
                onMouseEnter={() => setActive(c.key)}
                onFocus={() => setActive(c.key)}
                onClick={() => setActive(c.key)}
              >
                {c.value > 0 && max > 0 && <span className="colchart-bar" style={{ height: `${(c.value / max) * 100}%` }} />}
              </button>
            )
          })}
        </div>
      </div>
      <div className="colchart-ticks" aria-hidden="true">
        {columns.map((c) => (
          <span key={c.key}>{c.tick}</span>
        ))}
      </div>
      <figcaption className="colchart-readout" aria-live="polite">
        {current ? (
          <>
            {current.label}: <strong>{fmt(current.value, digits)}</strong> {unit}
          </>
        ) : (
          <span className="muted">Выберите столбик, чтобы увидеть число</span>
        )}
      </figcaption>
    </figure>
  )
}
