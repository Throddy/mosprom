import { useEffect, useState } from 'react'
import { errorText, getCameras, getRules, getStats } from './client.ts'
import type { Camera, RuleSpec } from './types.ts'

export interface TypeOption {
  type: string
  title: string
  // false: тип есть в событиях (/api/stats), но нет в /api/rules
  inRules: boolean
}

export interface Catalog {
  loading: boolean
  error: string | null
  cameras: Camera[]
  rules: RuleSpec[]
  types: TypeOption[]
  reload: () => void
}

// Справочники для фильтров и страницы камер: /api/cameras, /api/rules.
// Типы событий берутся из /api/rules и дополняются ключами by_type из /api/stats,
// чтобы в фильтре были типы уже сохранённых событий; список правил не задаётся во фронтенде
export function useCatalog(): Catalog {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<Omit<Catalog, 'reload'>>({
    loading: true,
    error: null,
    cameras: [],
    rules: [],
    types: [],
  })

  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller
    setState((s) => ({ ...s, loading: true }))
    Promise.all([getCameras(signal), getRules(signal), getStats(signal).catch(() => null)])
      .then(([cameras, rules, stats]) => {
        const types: TypeOption[] = rules.map((r) => ({ type: r.type, title: r.title, inRules: true }))
        for (const [type, count] of Object.entries(stats?.by_type ?? {})) {
          if (count > 0 && !types.some((t) => t.type === type)) types.push({ type, title: type, inRules: false })
        }
        setState({ loading: false, error: null, cameras, rules, types })
      })
      .catch((err: unknown) => {
        if (signal.aborted) return
        setState((s) => ({ ...s, loading: false, error: errorText(err) }))
      })
    return () => controller.abort()
  }, [attempt])

  return { ...state, reload: () => setAttempt((a) => a + 1) }
}
