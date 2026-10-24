import { useState } from 'react'

interface Props {
  url: string | null
  title: string
  className?: string
}

// Снимок события по snapshot_url; при null или ошибке загрузки — «Снимка нет»
export function Snapshot({ url, title, className = 'alert-snap' }: Props) {
  const [failed, setFailed] = useState(false)
  if (!url || failed) {
    return <div className={`${className} snap-empty`}>Снимка нет</div>
  }
  return (
    <a className={className} href={url} target="_blank" rel="noreferrer" title="Открыть снимок">
      <img src={url} alt={`Снимок: ${title}`} loading="lazy" onError={() => setFailed(true)} />
    </a>
  )
}
