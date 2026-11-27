/** График ЛК продукта: один ряд по дням, линия 2px с лёгкой заливкой, подсказка по наведению. SVG без библиотек. */

import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'

/** Цвет ряда на тёмной поверхности (синий из проверенной категориальной палитры, тёмный шаг). */
const SERIES_COLOR = 'var(--primary)'

function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const node = ref.current
    if (!node) return
    const update = () => setWidth(node.clientWidth)
    update()
    const observer = new ResizeObserver(update)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])
  return [ref, width]
}

/** «Красивый» верх шкалы и шаг сетки. */
export function niceScale(max: number, ticks = 4): { top: number; step: number } {
  if (max <= 0) return { top: ticks, step: 1 }
  const rough = max / ticks
  const power = 10 ** Math.floor(Math.log10(rough))
  const step = [1, 2, 5, 10].map((m) => m * power).find((value) => value >= rough) ?? 10 * power
  return { top: Math.ceil(max / step) * step, step }
}

const SHORT_DATE = new Intl.DateTimeFormat('ru-RU', { timeZone: 'UTC', day: 'numeric', month: 'short' })
const LONG_DATE = new Intl.DateTimeFormat('ru-RU', { timeZone: 'UTC', day: 'numeric', month: 'long', weekday: 'short' })
const shortDate = (iso: string) => SHORT_DATE.format(new Date(`${iso}T00:00:00Z`))
const longDate = (iso: string) => LONG_DATE.format(new Date(`${iso}T00:00:00Z`))

export function AreaChart({ dates, values, label }: { dates: string[]; values: number[]; label: string }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const height = 240
  const margin = { top: 10, right: 8, bottom: 26, left: 36 }
  const plotWidth = Math.max(width - margin.left - margin.right, 10)
  const plotHeight = height - margin.top - margin.bottom
  const { top, step } = niceScale(Math.max(0, ...values))
  const x = (index: number) => margin.left + (dates.length <= 1 ? plotWidth / 2 : (index / (dates.length - 1)) * plotWidth)
  const y = (value: number) => margin.top + plotHeight - (value / top) * plotHeight
  const tickEvery = Math.max(1, Math.ceil(dates.length / Math.max(2, Math.floor(plotWidth / 90))))
  const line = values.map((value, index) => `${x(index)},${y(value)}`).join(' ')
  const area = `${x(0)},${y(0)} ${line} ${x(values.length - 1)},${y(0)}`

  const onMove = (event: ReactPointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    const ratio = (event.clientX - box.left) / box.width
    setHover(Math.min(dates.length - 1, Math.max(0, Math.round(ratio * (dates.length - 1)))))
  }

  return (
    <div className="pl-chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={`${label} по дням`}>
          <defs>
            <linearGradient id="pl-area" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor={SERIES_COLOR} stopOpacity={0.22} />
              <stop offset="100%" stopColor={SERIES_COLOR} stopOpacity={0} />
            </linearGradient>
          </defs>
          {Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step).map((value) => (
            <g key={value}>
              <line className="pl-grid" x1={margin.left} x2={width - margin.right} y1={y(value)} y2={y(value)} />
              <text className="pl-axis" x={margin.left - 8} y={y(value)} textAnchor="end" dominantBaseline="middle">{value}</text>
            </g>
          ))}
          {dates.map((date, index) => index % tickEvery === 0 && (
            <text key={date} className="pl-axis" x={x(index)} y={height - 6} textAnchor="middle">{shortDate(date)}</text>
          ))}
          {dates.length > 1 ? (
            <>
              <polygon points={area} fill="url(#pl-area)" />
              <polyline points={line} fill="none" stroke={SERIES_COLOR} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
            </>
          ) : (
            <circle cx={x(0)} cy={y(values[0] ?? 0)} r={4} fill={SERIES_COLOR} />
          )}
          {hover !== null && (
            <g>
              <line className="pl-crosshair" x1={x(hover)} x2={x(hover)} y1={margin.top} y2={margin.top + plotHeight} />
              <circle cx={x(hover)} cy={y(values[hover] ?? 0)} r={4} fill={SERIES_COLOR} stroke="var(--surface)" strokeWidth={2} />
            </g>
          )}
          <rect x={margin.left} y={margin.top} width={plotWidth} height={plotHeight} fill="transparent"
            onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHover(null)} />
        </svg>
      )}
      {hover !== null && width > 0 && (
        <div className="pl-tooltip" style={{ left: Math.min(Math.max(x(hover) - 70, 0), width - 150) }}>
          <span>{longDate(dates[hover])}</span>
          <strong>{values[hover]}</strong>
        </div>
      )}
    </div>
  )
}
