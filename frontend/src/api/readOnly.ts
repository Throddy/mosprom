import { useSyncExternalStore } from 'react'
import { ApiError } from './client.ts'

// Режим «только просмотр» (публичный демо-стенд). В /api/status признака режима нет, поэтому он
// становится известен по первому ответу 403 на PATCH или PUT. Пробные запросы не отправляются.
// Скрытые кнопки только упрощают интерфейс: запрет изменений обеспечивает сервер
export const READ_ONLY_TITLE = 'Демонстрационный режим: только просмотр'

const KEY = 'linq.readOnly'
const listeners = new Set<() => void>()
let detail: string | null = load()

function load(): string | null {
  try {
    return window.sessionStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function isForbidden(err: unknown): err is ApiError {
  return err instanceof ApiError && err.status === 403
}

// Запоминает 403 от PATCH или PUT; возвращает true, если ошибка была отказом в изменении
export function noteForbidden(err: unknown): boolean {
  if (!isForbidden(err)) return false
  const text = err.detail ?? 'Сервер запретил изменения'
  if (detail !== text) {
    detail = text
    try {
      window.sessionStorage.setItem(KEY, text)
    } catch {
      // без sessionStorage режим действует до перезагрузки страницы
    }
    listeners.forEach((l) => l())
  }
  return true
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

// detail последнего отказа 403 или null, пока сервер изменения не запрещал
export function useReadOnly(): string | null {
  return useSyncExternalStore(subscribe, () => detail)
}
