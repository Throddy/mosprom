import type { EventStatus, EventView, EventsPage, Status } from './types.ts'

// Ошибка API: HTTP-код и текст из {"detail": "..."}
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch (err) {
    if (init?.signal?.aborted) throw err
    throw new ApiError(0, 'сервер недоступен')
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = `${detail}: ${body.detail}`
    } catch {
      // тело без JSON
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

export function getStatus(signal?: AbortSignal): Promise<Status> {
  return request<Status>('/api/status', { signal })
}

export function getEvents(limit: number, signal?: AbortSignal): Promise<EventsPage> {
  return request<EventsPage>(`/api/events?limit=${limit}`, { signal })
}

export function patchEvent(id: string, status: EventStatus, comment: string | null): Promise<EventView> {
  return request<EventView>(`/api/events/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, comment }),
  })
}

export function eventsSocketUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws/events`
}
