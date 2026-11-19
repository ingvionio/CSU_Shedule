/**
 * Графики ЛК продукта — SVG без библиотек.
 * Цвета и правила: тонкие линии 2px, столбцы ≤24px со скруглением 4px у вершины,
 * сетка в 1px, легенда и табличный вид (у двух цветов контраст ниже 3:1).
 */

import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'

/** Категориальные цвета в фиксированном порядке (проверены на различимость, в т. ч. при дальтонизме). */
export const SERIES_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100'] as const

export type Series = { key: string; label: string; color: string; values: number[] }

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

/** Линейный график по дням: легенда-переключатели, перекрестие с подсказкой, вид таблицей. */
export function LineChart({ dates, series, title }: { dates: string[]; series: Series[]; title: string }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const [hover, setHover] = useState<number | null>(null)
  const [asTable, setAsTable] = useState(false)
  const visible = series.filter((item) => !hidden.has(item.key))

  const height = 260
  const margin = { top: 12, right: 12, bottom: 28, left: 40 }
  const plotWidth = Math.max(width - margin.left - margin.right, 10)
  const plotHeight = height - margin.top - margin.bottom
  const max = Math.max(0, ...visible.flatMap((item) => item.values))
  const { top, step } = niceScale(max)
  const x = (index: number) => margin.left + (dates.length <= 1 ? plotWidth / 2 : (index / (dates.length - 1)) * plotWidth)
  const y = (value: number) => margin.top + plotHeight - (value / top) * plotHeight
  const tickEvery = Math.max(1, Math.ceil(dates.length / Math.max(2, Math.floor(plotWidth / 80))))

  const toggle = (key: string) => setHidden((current) => {
    const next = new Set(current)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    return next
  })

  const onMove = (event: ReactPointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    const ratio = (event.clientX - box.left) / box.width
    setHover(Math.min(dates.length - 1, Math.max(0, Math.round(ratio * (dates.length - 1)))))
  }

  return (
    <div className="chart">
      <div className="chart-toolbar">
        <div className="chart-legend" role="group" aria-label={`Ряды: ${title}`}>
          {series.map((item) => (
            <button key={item.key} type="button" aria-pressed={!hidden.has(item.key)} onClick={() => toggle(item.key)}
              className={hidden.has(item.key) ? 'off' : ''}>
              <span className="chart-swatch" style={{ background: item.color }} />{item.label}
            </button>
          ))}
        </div>
        <button type="button" className="chart-view-toggle" onClick={() => setAsTable(!asTable)}>
          {asTable ? 'График' : 'Таблица'}
        </button>
      </div>

      {asTable ? (
        <div className="import-table-scroll chart-table">
          <table className="import-table product-table">
            <caption className="sr-only">{title}</caption>
            <thead><tr><th>День</th>{series.map((item) => <th key={item.key}>{item.label}</th>)}</tr></thead>
            <tbody>
              {dates.map((date, index) => ({ date, index })).reverse().map(({ date, index }) => (
                <tr key={date}><td>{longDate(date)}</td>{series.map((item) => <td key={item.key}>{item.values[index]}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="chart-plot" ref={ref}>
          {width > 0 && (
            <svg width={width} height={height} role="img" aria-label={title}>
              {Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step).map((value) => (
                <g key={value}>
                  <line className="chart-grid" x1={margin.left} x2={width - margin.right} y1={y(value)} y2={y(value)} />
                  <text className="chart-axis" x={margin.left - 8} y={y(value)} textAnchor="end" dominantBaseline="middle">{value}</text>
                </g>
              ))}
              {dates.map((date, index) => index % tickEvery === 0 && (
                <text key={date} className="chart-axis" x={x(index)} y={height - 8} textAnchor="middle">{shortDate(date)}</text>
              ))}
              {visible.map((item) => (
                dates.length > 1
                  ? <polyline key={item.key} fill="none" stroke={item.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"
                      points={item.values.map((value, index) => `${x(index)},${y(value)}`).join(' ')} />
                  : <circle key={item.key} cx={x(0)} cy={y(item.values[0] ?? 0)} r={4} fill={item.color} stroke="var(--surface)" strokeWidth={2} />
              ))}
              {hover !== null && (
                <g>
                  <line className="chart-crosshair" x1={x(hover)} x2={x(hover)} y1={margin.top} y2={margin.top + plotHeight} />
                  {visible.map((item) => (
                    <circle key={item.key} cx={x(hover)} cy={y(item.values[hover] ?? 0)} r={4} fill={item.color} stroke="var(--surface)" strokeWidth={2} />
                  ))}
                </g>
              )}
              <rect x={margin.left} y={margin.top} width={plotWidth} height={plotHeight} fill="transparent"
                onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHover(null)} />
            </svg>
          )}
          {hover !== null && width > 0 && (
            <div className="chart-tooltip" style={{ left: Math.min(x(hover) + 12, width - 180), top: margin.top }}>
              <strong>{longDate(dates[hover])}</strong>
              {visible.map((item) => (
                <span key={item.key}><i className="chart-swatch" style={{ background: item.color }} />{item.label}<b>{item.values[hover]}</b></span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export type Column = { label: string; value: number; note?: string }

/** Столбчатая диаграмма (воронка): подпись значения над столбцом, доля перехода под подписью шага. */
export function ColumnChart({ columns, title, color = SERIES_COLORS[0] }: { columns: Column[]; title: string; color?: string }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const height = 220
  const margin = { top: 24, bottom: 8 }
  const plotHeight = height - margin.top - margin.bottom
  const { top } = niceScale(Math.max(0, ...columns.map((column) => column.value)))
  const slot = width / Math.max(columns.length, 1)
  const barWidth = 24

  return (
    <div className="chart">
      <div className="chart-plot" ref={ref}>
        {width > 0 && (
          <svg width={width} height={height} role="img" aria-label={title}>
            <line className="chart-grid" x1={0} x2={width} y1={margin.top + plotHeight} y2={margin.top + plotHeight} />
            {columns.map((column, index) => {
              const barHeight = column.value > 0 ? Math.max((column.value / top) * plotHeight, 2) : 0
              const cx = slot * index + slot / 2
              const yTop = margin.top + plotHeight - barHeight
              const r = Math.min(4, barHeight)
              return (
                <g key={column.label}>
                  <title>{`${column.label}: ${column.value}${column.note ? ` (${column.note})` : ''}`}</title>
                  {barHeight > 0 && (
                    <path fill={color} d={`M${cx - barWidth / 2},${margin.top + plotHeight} V${yTop + r} Q${cx - barWidth / 2},${yTop} ${cx - barWidth / 2 + r},${yTop} H${cx + barWidth / 2 - r} Q${cx + barWidth / 2},${yTop} ${cx + barWidth / 2},${yTop + r} V${margin.top + plotHeight} Z`} />
                  )}
                  <text className="chart-value" x={cx} y={yTop - 6} textAnchor="middle">{column.value}</text>
                  <rect x={slot * index} y={0} width={slot} height={height} fill="transparent" />
                </g>
              )
            })}
          </svg>
        )}
      </div>
      <ol className="chart-columns-labels" style={{ gridTemplateColumns: `repeat(${columns.length}, 1fr)` }}>
        {columns.map((column) => (
          <li key={column.label}><span>{column.label}</span>{column.note && <small>{column.note}</small>}</li>
        ))}
      </ol>
    </div>
  )
}

export type BarRow = { key: string; label: string; value: number; caption?: string }

/** Горизонтальные полосы: длинные подписи слева, значение справа от полосы. */
export function BarList({ rows, title, color = SERIES_COLORS[0] }: { rows: BarRow[]; title: string; color?: string }) {
  const max = useMemo(() => Math.max(1, ...rows.map((row) => row.value)), [rows])
  return (
    <ul className="bar-list" aria-label={title}>
      {rows.map((row) => (
        <li key={row.key} title={`${row.label}: ${row.caption ?? row.value}`}>
          <span className="bar-list-label">{row.label}</span>
          <span className="bar-list-track">
            {row.value > 0 && <span className="bar-list-bar" style={{ width: `${(row.value / max) * 100}%`, background: color }} />}
          </span>
          <span className="bar-list-value">{row.caption ?? row.value}</span>
        </li>
      ))}
    </ul>
  )
}
