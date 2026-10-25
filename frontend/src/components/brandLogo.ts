import logoOnDarkSvg from '../assets/logo-dark.svg?raw'
import logoOnLightSvg from '../assets/logo-light.svg?raw'
import type { Theme } from './useTheme.ts'

// Фирменный логотип в шапке. logo-dark.svg — белая надпись для тёмного фона,
// logo-light.svg — чёрная для светлого. Выбор зависит от фона шапки в текущей теме:
// шапка тёмная в обеих темах (--bar в index.css), поэтому в ней нужна белая версия.
// Если шапку светлой темы сделать светлой, достаточно поменять тон здесь
const HEADER_TONE: Record<Theme, 'dark' | 'light'> = { light: 'dark', dark: 'dark' }

export interface Logo {
  src: string
  // ширина к высоте видимой надписи
  ratio: number
}

// В исходных файлах вокруг надписи большие поля (viewBox 2170×725, надпись ~2070×310).
// Границы считаются по точкам контура, если путь состоит из абсолютных M, L, Z; иначе файл берётся как есть
function crop(svg: string): Logo {
  const box = svg.match(/viewBox="([\d.\s-]+)"/)?.[1].trim().split(/\s+/).map(Number) ?? [0, 0, 1, 1]
  const paths = [...svg.matchAll(/\sd="([^"]+)"/g)].map((m) => m[1])
  const simple = paths.length > 0 && paths.every((d) => /^[MLZ\d.\s,-]+$/.test(d))
  let [x, y, w, h] = box
  if (simple) {
    const nums = paths.flatMap((d) => (d.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number))
    const xs = nums.filter((_, i) => i % 2 === 0)
    const ys = nums.filter((_, i) => i % 2 === 1)
    const pad = (Math.max(...ys) - Math.min(...ys)) * 0.04
    x = Math.min(...xs) - pad
    y = Math.min(...ys) - pad
    w = Math.max(...xs) - Math.min(...xs) + pad * 2
    h = Math.max(...ys) - Math.min(...ys) + pad * 2
  }
  const out = svg
    .replace(/viewBox="[^"]*"/, `viewBox="${x} ${y} ${w} ${h}"`)
    .replace(/\swidth="[^"]*"/, '')
    .replace(/\sheight="[^"]*"/, '')
  return { src: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(out)}`, ratio: w / h }
}

const ON_DARK = crop(logoOnDarkSvg)
const ON_LIGHT = crop(logoOnLightSvg)

export function headerLogo(theme: Theme): Logo {
  return HEADER_TONE[theme] === 'dark' ? ON_DARK : ON_LIGHT
}
