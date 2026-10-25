import { useEffect, useState } from 'react'

// Текущее время с обновлением раз в intervalMs, для подписей «5 мин назад»
export function useNow(intervalMs = 30000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(timer)
  }, [intervalMs])
  return now
}
