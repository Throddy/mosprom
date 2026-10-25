const timeFmt = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const dateFmt = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit' })

// Unix-время в секундах → «10:15:03» для сегодняшних событий, «23.10 10:15:03» для остальных
export function formatTs(ts: number, now = new Date()): string {
  const d = new Date(ts * 1000)
  const time = timeFmt.format(d)
  return d.toDateString() === now.toDateString() ? time : `${dateFmt.format(d)} ${time}`
}

// Имя зоны; без zone_name — её id; без зоны — null
export function zoneLabel(event: { zone_name: string | null; zone_id: string | null }): string | null {
  return event.zone_name ?? event.zone_id
}

// Unix-секунды → значение <input type="datetime-local"> в местном времени
export function toLocalInput(ts: number): string {
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function fromLocalInput(value: string): number | undefined {
  if (!value) return undefined
  const ms = new Date(value).getTime()
  return Number.isNaN(ms) ? undefined : Math.floor(ms / 1000)
}

const fullFmt = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

export function formatFull(ts: number): string {
  return fullFmt.format(new Date(ts * 1000))
}

// «только что», «5 мин назад», «3 ч назад»; старше суток — null, достаточно даты
export function formatAgo(ts: number, nowMs = Date.now()): string | null {
  const sec = Math.floor(nowMs / 1000 - ts)
  if (sec < 60) return 'только что'
  if (sec < 3600) return `${Math.floor(sec / 60)} мин назад`
  if (sec < 24 * 3600) return `${Math.floor(sec / 3600)} ч назад`
  return null
}

export function formatDuration(sec: number): string {
  const s = Math.max(0, Math.round(sec))
  if (s < 60) return `${s} с`
  const m = Math.floor(s / 60)
  if (m < 60) return s % 60 ? `${m} мин ${s % 60} с` : `${m} мин`
  const h = Math.floor(m / 60)
  return m % 60 ? `${h} ч ${m % 60} мин` : `${h} ч`
}
