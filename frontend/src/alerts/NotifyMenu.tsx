import { useEffect, useRef, useState } from 'react'
import { IconBell, IconBellOff } from '../components/Icons.tsx'
import type { NotifySettings } from './notifySettings.ts'

interface Props {
  settings: NotifySettings
  onChange: (patch: Partial<NotifySettings>) => void
}

// Кнопка с колокольчиком в шапке и меню с двумя переключателями
export function NotifyMenu({ settings, onChange }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="notify" ref={ref}>
      <button
        type="button"
        className="icon-btn"
        aria-expanded={open}
        aria-controls="notify-menu"
        aria-label="Настройки уведомлений"
        title={settings.enabled ? 'Настройки уведомлений' : 'Уведомления выключены'}
        onClick={() => setOpen((o) => !o)}
      >
        {settings.enabled ? <IconBell /> : <IconBellOff />}
      </button>
      {open && (
        <div className="notify-menu" id="notify-menu" role="group" aria-label="Всплывающие уведомления">
          <p className="notify-title">Всплывающие уведомления</p>
          <label className="notify-row">
            <span>Показывать уведомления</span>
            <span className="switch">
              <input type="checkbox" role="switch" checked={settings.enabled} onChange={(e) => onChange({ enabled: e.target.checked })} />
            </span>
          </label>
          <label className={settings.enabled ? 'notify-row' : 'notify-row notify-row-off'}>
            <span>Только критические</span>
            <span className="switch">
              <input
                type="checkbox"
                role="switch"
                checked={settings.criticalOnly}
                disabled={!settings.enabled}
                onChange={(e) => onChange({ criticalOnly: e.target.checked })}
              />
            </span>
          </label>
          <p className="notify-help">Тревоги всё равно приходят в раздел «Тревоги», журнал и монитор.</p>
        </div>
      )}
    </div>
  )
}
