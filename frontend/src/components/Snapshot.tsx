import { useState } from 'react'

interface Props {
  url: string | null
  title: string
  className?: string
  // задан: нажатие открывает подробности тревоги; иначе снимок открывается в новой вкладке
  onOpen?: () => void
}

// Снимок события по snapshot_url; при null или ошибке загрузки — «Снимка нет»
export function Snapshot({ url, title, className = 'snap', onOpen }: Props) {
  const [failed, setFailed] = useState(false)
  const empty = !url || failed
  const content = empty ? (
    <span className="snap-empty">Снимка нет</span>
  ) : (
    <img src={url} alt={`Кадр: ${title}`} loading="lazy" onError={() => setFailed(true)} />
  )

  if (onOpen) {
    return (
      <button type="button" className={`${className} snap-button`} onClick={onOpen} aria-label={`Открыть тревогу: ${title}`}>
        {content}
      </button>
    )
  }
  if (empty) return <div className={className}>{content}</div>
  return (
    <a className={className} href={url} target="_blank" rel="noreferrer" title="Открыть снимок в полном размере">
      {content}
    </a>
  )
}
