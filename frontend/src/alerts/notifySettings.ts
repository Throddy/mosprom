import { useCallback, useState } from 'react'

// Настройки всплывающих уведомлений. Влияют только на всплывающие окна: лента, счётчики,
// журнал и монитор получают тревоги всегда
export interface NotifySettings {
  enabled: boolean
  criticalOnly: boolean
}

const KEY = 'linq.notify'
const DEFAULTS: NotifySettings = { enabled: true, criticalOnly: false }

function load(): NotifySettings {
  try {
    const raw = window.localStorage.getItem(KEY)
    if (!raw) return DEFAULTS
    const v = JSON.parse(raw) as Partial<NotifySettings>
    return { enabled: v.enabled !== false, criticalOnly: v.criticalOnly === true }
  } catch {
    return DEFAULTS
  }
}

export function useNotifySettings(): [NotifySettings, (patch: Partial<NotifySettings>) => void] {
  const [settings, setSettings] = useState<NotifySettings>(load)
  const update = useCallback((patch: Partial<NotifySettings>) => {
    setSettings((s) => {
      const next = { ...s, ...patch }
      try {
        window.localStorage.setItem(KEY, JSON.stringify(next))
      } catch {
        // без localStorage настройка действует до перезагрузки
      }
      return next
    })
  }, [])
  return [settings, update]
}

// Показывать ли всплывающее уведомление о тревоге с такой опасностью
export function shouldNotify(settings: NotifySettings, severity: string): boolean {
  return settings.enabled && (!settings.criticalOnly || severity === 'critical')
}
