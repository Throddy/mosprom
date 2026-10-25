import { useCallback, useEffect, useState } from 'react'

export type Theme = 'dark' | 'light'

const KEY = 'linq.theme'
const DARK = '(prefers-color-scheme: dark)'

function stored(): Theme | null {
  try {
    const v = window.localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : null
  } catch {
    return null
  }
}

// Тема по умолчанию как в системе. Переключатель запоминает выбор в браузере этого зрителя,
// тогда тема задаётся атрибутом data-theme на <html>
export function useTheme(): { theme: Theme; toggle: () => void } {
  const [choice, setChoice] = useState<Theme | null>(stored)
  const [system, setSystem] = useState<Theme>(() => (window.matchMedia(DARK).matches ? 'dark' : 'light'))
  const theme = choice ?? system

  useEffect(() => {
    const mq = window.matchMedia(DARK)
    const update = () => setSystem(mq.matches ? 'dark' : 'light')
    mq.addEventListener('change', update)
    return () => mq.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    const root = document.documentElement
    if (choice) root.dataset.theme = choice
    else delete root.dataset.theme
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#16191c' : '#f3f4f5')
    try {
      if (choice) window.localStorage.setItem(KEY, choice)
    } catch {
      // без localStorage выбор действует до перезагрузки
    }
  }, [choice, theme])

  const toggle = useCallback(() => setChoice(theme === 'dark' ? 'light' : 'dark'), [theme])
  return { theme, toggle }
}
