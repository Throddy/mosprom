import type { ReactNode } from 'react'
import type { Async } from './useAsync.ts'

const timeFmt = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

interface SectionProps<T> {
  id: string
  title: string
  // откуда данные: путь API, виден в подсказке
  source: string
  actions?: ReactNode
  state: Async<T>
  onRetry: () => void
  // что не загрузилось, для текста ошибки
  what: string
  children: ReactNode
}

// Раздел страницы со своими загрузкой и ошибкой: отказ одного API не ломает остальные разделы
export function Section<T>({ id, title, source, actions, state, onRetry, what, children }: SectionProps<T>) {
  return (
    <section className="an-section" id={`section-${id}`} aria-labelledby={`an-${id}`} data-section={id} data-source={source}>
      <div className="an-head">
        <div>
          <h3 id={`an-${id}`}>{title}</h3>
          {state.state === 'ok' && (
            <p className="muted small an-source" title={`Источник: ${source}`}>
              Обновлено в {timeFmt.format(state.at)}
            </p>
          )}
        </div>
        {actions && <div className="an-actions">{actions}</div>}
      </div>
      {state.state === 'error' && (
        <div className="notice notice-error" role="alert">
          <span>
            Не удалось загрузить {what}: {state.error}
          </span>
          <button type="button" className="btn" onClick={onRetry}>
            Повторить
          </button>
        </div>
      )}
      {state.state === 'loading' && state.data === null && <p className="empty">Загружаем…</p>}
      {state.data !== null && <div className={state.state === 'loading' ? 'an-body stale' : 'an-body'}>{children}</div>}
    </section>
  )
}

export function SourceNote({ kind, children }: { kind?: 'test'; children: ReactNode }) {
  return <p className={kind === 'test' ? 'an-note an-note-test' : 'an-note muted'}>{children}</p>
}

export function StatTile({ label, value, unit, note }: { label: string; value: string; unit?: string; note?: string }) {
  return (
    <div className="stat-tile">
      <div className="stat-label">{label}</div>
      <div className="stat-value">
        {value}
        {unit && <span className="stat-unit"> {unit}</span>}
      </div>
      {note && <div className="stat-note muted">{note}</div>}
    </div>
  )
}
