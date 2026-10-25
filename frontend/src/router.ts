import { useEffect, useState } from 'react'

// Маршруты в hash: бэкенд раздаёт frontend/dist без отката на index.html,
// поэтому адрес вида /journal при обновлении страницы дал бы 404
export type Page = 'overview' | 'monitor' | 'alerts' | 'journal' | 'cameras' | 'analytics'

export interface Route {
  page: Page
  params: URLSearchParams
}

const PAGES: Page[] = ['overview', 'monitor', 'alerts', 'journal', 'cameras', 'analytics']

export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#\/?/, '')
  const [path, query = ''] = raw.split('?', 2)
  const page = PAGES.find((p) => p === path) ?? 'overview'
  return { page, params: new URLSearchParams(query) }
}

export function routeHref(page: Page, params?: URLSearchParams | Record<string, string>): string {
  const qs = new URLSearchParams(params).toString()
  return qs ? `#/${page}?${qs}` : `#/${page}`
}

export function navigate(href: string, replace = false): void {
  if (href === window.location.hash) return
  if (replace) {
    window.history.replaceState(null, '', href)
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  } else {
    window.location.hash = href
  }
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseHash(window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}
