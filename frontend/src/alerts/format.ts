const timeFmt = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const dateFmt = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit' })

// Unix-время в секундах → «10:15:03» для сегодняшних событий, «23.10 10:15:03» для остальных
export function formatTs(ts: number, now = new Date()): string {
  const d = new Date(ts * 1000)
  const time = timeFmt.format(d)
  return d.toDateString() === now.toDateString() ? time : `${dateFmt.format(d)} ${time}`
}

export function formatDuration(sec: number): string {
  const s = Math.max(0, Math.round(sec))
  if (s < 60) return `${s} с`
  const m = Math.floor(s / 60)
  if (m < 60) return s % 60 ? `${m} мин ${s % 60} с` : `${m} мин`
  const h = Math.floor(m / 60)
  return m % 60 ? `${h} ч ${m % 60} мин` : `${h} ч`
}
