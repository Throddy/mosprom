import onDarkTabsSvg from './assets/sokol-favicon.svg?raw'
import darkWordmarkSvg from './assets/logo-light.svg?raw'

// Иконка вкладки. Белая «С» с соколом (sokol-favicon.svg) — для тёмной панели вкладок,
// тёмная — та же буква «С» из начала чёрной надписи logo-light.svg — для светлой.
// Цвет панели вкладок следует теме браузера и системы (prefers-color-scheme), а не теме сайта.
// Файлы не меняются: у копии в памяти только квадратный viewBox вокруг рисунка без лишних полей

interface Box {
  x0: number
  x1: number
  y0: number
  y1: number
}

// Координаты точек путей: только для абсолютных команд и без transform; иначе null — файл берётся как есть
function subpathBoxes(svg: string): Box[] | null {
  if (/transform=/.test(svg)) return null
  const paths = [...svg.matchAll(/\sd="([^"]+)"/g)].map((m) => m[1])
  if (paths.length === 0 || !paths.every((d) => /^[MLCQZ\d.\s,-]+$/.test(d))) return null
  // точки кривых вместе с контрольными: рамка не меньше рисунка
  return paths.flatMap((d) =>
    d
      .split(/(?=M)/)
      .filter((p) => p.trim())
      .map((p) => {
        const n = (p.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number)
        const xs = n.filter((_, i) => i % 2 === 0)
        const ys = n.filter((_, i) => i % 2 === 1)
        return { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) }
      }),
  )
}

// Квадратный viewBox вокруг рисунка; padX не даёт захватить соседний знак справа
function squareIcon(svg: string, box: Box, padX: number): string {
  const w = box.x1 - box.x0
  const h = box.y1 - box.y0
  const side = Math.max(w + padX * 2, h * 1.08)
  const cx = (box.x0 + box.x1) / 2
  const cy = (box.y0 + box.y1) / 2
  const out = svg
    .replace(/viewBox="[^"]*"/, `viewBox="${cx - side / 2} ${cy - side / 2} ${side} ${side}"`)
    .replace(/(<svg[^>]*?)\swidth="[^"]*"/, '$1')
    .replace(/(<svg[^>]*?)\sheight="[^"]*"/, '$1')
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(out)}`
}

function whiteIcon(): string | null {
  const boxes = subpathBoxes(onDarkTabsSvg)
  if (!boxes) return null
  const box = {
    x0: Math.min(...boxes.map((b) => b.x0)),
    x1: Math.max(...boxes.map((b) => b.x1)),
    y0: Math.min(...boxes.map((b) => b.y0)),
    y1: Math.max(...boxes.map((b) => b.y1)),
  }
  return squareIcon(onDarkTabsSvg, box, (box.x1 - box.x0) * 0.04)
}

// Первый знак надписи «СОКОЛ»: контуры, которые перекрываются по горизонтали с самым левым
function darkIcon(): string | null {
  const boxes = subpathBoxes(darkWordmarkSvg)
  if (!boxes) return null
  const sorted = [...boxes].sort((a, b) => a.x0 - b.x0)
  const glyph = { ...sorted[0] }
  let next = Infinity
  for (const b of sorted.slice(1)) {
    if (b.x0 <= glyph.x1) {
      glyph.x1 = Math.max(glyph.x1, b.x1)
      glyph.y0 = Math.min(glyph.y0, b.y0)
      glyph.y1 = Math.max(glyph.y1, b.y1)
    } else {
      next = b.x0
      break
    }
  }
  const gap = next - glyph.x1
  return squareIcon(darkWordmarkSvg, glyph, Math.min((glyph.x1 - glyph.x0) * 0.04, gap / 2 - 1))
}

export function setupFavicon(): void {
  const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
  const white = whiteIcon()
  const dark = darkIcon()
  if (!link || !white || !dark) return
  const mq = window.matchMedia('(prefers-color-scheme: dark)')
  const apply = () => {
    link.href = mq.matches ? white : dark
    link.dataset.variant = mq.matches ? 'white' : 'dark'
  }
  apply()
  mq.addEventListener('change', apply)
}
