import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import type { Zone } from '../api/types.ts'
import { MAX_POINTS, normalizePoint, type Point } from './editorModel.ts'

interface Props {
  // null: кадра нет, разметка на пустом поле 16:9
  imageUrl: string | null
  zones: Zone[]
  selectedZone: string | null
  selectedPoint: number | null
  // false: только просмотр зон, без добавления и перетаскивания точек
  editable: boolean
  onSelectZone: (zoneId: string) => void
  onSelectPoint: (index: number | null) => void
  onAddPoint: (p: Point) => void
  // gesture: номер жеста перетаскивания, правки одного жеста отменяются одним шагом
  onMovePoint: (index: number, p: Point, gesture: number) => void
}

const VERTEX_R = 8
// Область касания точки больше видимого кружка: палец закрывает около 1 см
const VERTEX_HIT_R = 20
// Точка ставится коротким нажатием; движение дальше этого порога — не нажатие
const TAP_PX = 10

// Кадр и полигоны зон. SVG лежит точно поверх показанного изображения, поэтому
// координаты считаются от его прямоугольника и не зависят от масштаба и размера кадра
export function ZoneCanvas({
  imageUrl,
  zones,
  selectedZone,
  selectedPoint,
  editable,
  onSelectZone,
  onSelectPoint,
  onAddPoint,
  onMovePoint,
}: Props) {
  const boxRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const drag = useRef<{ index: number; gesture: number } | null>(null)
  const tap = useRef<{ id: number; x: number; y: number } | null>(null)
  const gestures = useRef(0)

  useEffect(() => {
    const box = boxRef.current
    if (!box) return
    const update = () => setSize({ w: box.clientWidth, h: box.clientHeight })
    update()
    const observer = new ResizeObserver(update)
    observer.observe(box)
    return () => observer.disconnect()
  }, [])

  const toPoint = (e: { clientX: number; clientY: number }) => {
    const rect = boxRef.current!.getBoundingClientRect()
    return normalizePoint(e.clientX, e.clientY, rect)
  }

  const active = zones.find((z) => z.id === selectedZone) ?? null
  const full = active !== null && active.polygon.length >= MAX_POINTS
  const drawing = editable && active !== null

  const onBackgroundDown = (e: ReactPointerEvent<SVGSVGElement>) => {
    if (e.button !== 0 || !drawing || full) return
    tap.current = { id: e.pointerId, x: e.clientX, y: e.clientY }
  }

  const onBackgroundUp = (e: ReactPointerEvent<SVGSVGElement>) => {
    const t = tap.current
    tap.current = null
    if (!t || t.id !== e.pointerId || !drawing || full) return
    if (Math.hypot(e.clientX - t.x, e.clientY - t.y) > TAP_PX) return
    onAddPoint(toPoint(e))
  }

  const onVertexDown = (e: ReactPointerEvent<SVGCircleElement>, index: number) => {
    if (e.button !== 0) return
    e.stopPropagation()
    onSelectPoint(index)
    if (!editable) return
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { index, gesture: ++gestures.current }
  }

  const onVertexMove = (e: ReactPointerEvent<SVGCircleElement>) => {
    if (!drag.current) return
    onMovePoint(drag.current.index, toPoint(e), drag.current.gesture)
  }

  const onVertexUp = () => {
    drag.current = null
  }

  const px = ([x, y]: Point | [number, number]) => `${x * size.w},${y * size.h}`

  return (
    <div className={`zone-canvas${drawing ? ' zone-canvas-edit' : ''}${drawing && !full ? ' zone-canvas-add' : ''}`} ref={boxRef}>
      {imageUrl ? (
        <img src={imageUrl} alt="Кадр камеры для разметки зон" draggable={false} />
      ) : (
        <div className="zone-canvas-blank" />
      )}
      <svg
        className="zone-canvas-svg"
        width={size.w}
        height={size.h}
        onPointerDown={onBackgroundDown}
        onPointerUp={onBackgroundUp}
        onPointerCancel={() => {
          tap.current = null
        }}
        role="img"
        aria-label="Опасные зоны на кадре"
      >
        {zones.map((z) => {
          const isActive = z.id === selectedZone
          const pts = z.polygon.map(px).join(' ')
          return (
            <g key={z.id} className={isActive ? 'zone zone-active' : 'zone'} data-zone-id={z.id}>
              {z.polygon.length >= 3 ? (
                <polygon
                  points={pts}
                  onPointerDown={(e) => {
                    if (!isActive) {
                      e.stopPropagation()
                      onSelectZone(z.id)
                    }
                  }}
                />
              ) : (
                <polyline points={pts} />
              )}
              {isActive &&
                z.polygon.map((p, i) => (
                  <g key={i} className={i === selectedPoint ? 'vertex vertex-selected' : 'vertex'}>
                    <circle className="vertex-dot" cx={p[0] * size.w} cy={p[1] * size.h} r={VERTEX_R} />
                    <circle
                      className="vertex-hit"
                      data-index={i}
                      cx={p[0] * size.w}
                      cy={p[1] * size.h}
                      r={VERTEX_HIT_R}
                      onPointerDown={(e) => onVertexDown(e, i)}
                      onPointerMove={onVertexMove}
                      onPointerUp={onVertexUp}
                      onPointerCancel={onVertexUp}
                    />
                  </g>
                ))}
              {!isActive && z.polygon.length > 0 && (
                <text x={z.polygon[0][0] * size.w + 6} y={z.polygon[0][1] * size.h - 6} className="zone-label">
                  {z.name}
                </text>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
