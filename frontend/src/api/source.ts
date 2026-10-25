import type { ServerStatus } from './useServerStatus.ts'
import type { Status } from './types.ts'

// Откуда тревоги: только по /api/status. backend = fixtures — тестовые события сервера (PIPELINE=0),
// onnx и linq — результат нейросети (PIPELINE=1), CONTRACT.md, раздел 4
export interface DataSource {
  test: boolean
  label: string
  detail: string
}

export function dataSource(status: Status): DataSource {
  if (status.backend === 'fixtures') {
    return {
      test: true,
      label: 'Тестовые данные',
      detail: 'Сервер в тестовом режиме: тревоги созданы для проверки интерфейса, это не результат нейросети.',
    }
  }
  if (status.backend === 'linq') {
    return { test: false, label: 'Нейросеть на LinQ TPU', detail: `Модель ${status.detector} на ускорителе LinQ.` }
  }
  if (status.backend === 'onnx') {
    return { test: false, label: 'Нейросеть на процессоре', detail: `Модель ${status.detector}, ONNX Runtime на CPU.` }
  }
  return { test: false, label: `Детектор ${status.backend}`, detail: `Модель ${status.detector}.` }
}

// Последний известный статус: при потере связи берётся сохранённый
export function knownStatus(server: ServerStatus): Status | null {
  if (server.state === 'online') return server.status
  if (server.state === 'offline') return server.last
  return null
}

export function isTestMode(server: ServerStatus): boolean {
  const status = knownStatus(server)
  return status !== null && status.backend === 'fixtures'
}
