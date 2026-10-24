import type { Camera, EventStatus, EventView, EventsPage, EventsQuery, RuleSpec, Stats, Status } from './types.ts'

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

export function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

export function getStatus(signal?: AbortSignal): Promise<Status> {
  return request<Status>('/api/status', { signal })
}

export function eventsPath(query: EventsQuery): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `/api/events?${qs}` : '/api/events'
}

export function getEvents(query: EventsQuery, signal?: AbortSignal): Promise<EventsPage> {
  return request<EventsPage>(eventsPath(query), { signal })
}

export function patchEvent(id: string, status: EventStatus, comment: string | null): Promise<EventView> {
  return request<EventView>(`/api/events/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, comment }),
  })
}

export function getCameras(signal?: AbortSignal): Promise<Camera[]> {
  return request<Camera[]>('/api/cameras', { signal })
}

export function getRules(signal?: AbortSignal): Promise<RuleSpec[]> {
  return request<RuleSpec[]>('/api/rules', { signal })
}

export function getStats(signal?: AbortSignal): Promise<Stats> {
  return request<Stats>('/api/stats', { signal })
}

export function streamUrl(cameraId: string): string {
  return `/api/cameras/${encodeURIComponent(cameraId)}/stream`
}

export function eventsSocketUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws/events`
}
