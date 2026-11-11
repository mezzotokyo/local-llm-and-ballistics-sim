import type { TrajectoryPoint } from '../types'

export type ChartView = 'xy' | 'xz'

interface TrajectoryChartProps {
  trajectory: TrajectoryPoint[]
  idealRange: number | null
  groundRange: number | null
  centralBody?: boolean
  view?: ChartView
}

const WIDTH = 940
const HEIGHT = 460
const MARGIN = { top: 28, right: 28, bottom: 52, left: 68 }

function niceStep(range: number, count: number): number {
  if (range <= 0) {
    return 1
  }
  const raw = range / count
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const normalized = raw / magnitude
  const nice = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10
  return nice * magnitude
}

function axisTicks(low: number, high: number, count: number): number[] {
  const step = niceStep(high - low, count)
  const start = Math.floor(low / step) * step
  const values: number[] = []
  for (let value = start; value <= high + step / 2; value += step) {
    if (value >= low - step / 2) {
      values.push(Number(value.toFixed(6)))
    }
  }
  return values
}

interface Domain {
  xLo: number
  xHi: number
  yLo: number
  yHi: number
}

function chartDomain(
  trajectory: TrajectoryPoint[],
  idealRange: number | null,
  groundRange: number | null,
  centralBody: boolean,
  view: ChartView,
): Domain {
  const xs = trajectory.map((p) => p.x)
  const ys = trajectory.map((p) => (view === 'xz' ? p.z : p.y))
  if (idealRange !== null && idealRange > 0) {
    xs.push(idealRange)
  }
  if (groundRange !== null && groundRange > 0) {
    xs.push(groundRange)
  }

  if (!centralBody) {
    return {
      xLo: 0,
      xHi: Math.max(...xs, 1) * 1.05,
      yLo: Math.min(...ys, 0),
      yHi: Math.max(...ys, 1) * 1.15,
    }
  }

  const xLo = Math.min(...xs, 0)
  const xHi = Math.max(...xs, 0)
  const yLo = Math.min(...ys, 0)
  const yHi = Math.max(...ys, 0)
  const span = Math.max(xHi - xLo, yHi - yLo, 1)
  const pad = span * 0.06
  return { xLo: xLo - pad, xHi: xHi + pad, yLo: yLo - pad, yHi: yHi + pad }
}

export function TrajectoryChart({
  trajectory,
  idealRange,
  groundRange,
  centralBody = false,
  view = 'xy',
}: TrajectoryChartProps) {
  const plotWidth = WIDTH - MARGIN.left - MARGIN.right
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom

  const { xLo, xHi, yLo, yHi } = chartDomain(
    trajectory,
    idealRange,
    groundRange,
    centralBody,
    view,
  )

  const height = (p: TrajectoryPoint) => (view === 'xz' ? p.z : p.y)

  const sx = (x: number) => MARGIN.left + ((x - xLo) / (xHi - xLo)) * plotWidth
  const sy = (y: number) => MARGIN.top + plotHeight - ((y - yLo) / (yHi - yLo)) * plotHeight

  const path = trajectory
    .map((p, index) => `${index === 0 ? 'M' : 'L'} ${sx(p.x).toFixed(2)} ${sy(height(p)).toFixed(2)}`)
    .join(' ')

  const xTicks = axisTicks(xLo, xHi, 6)
  const yTicks = axisTicks(yLo, yHi, 5)
  const xAxis = xLo <= 0 && 0 <= xHi ? sx(0) : MARGIN.left
  const yAxis = yLo <= 0 && 0 <= yHi ? sy(0) : MARGIN.top + plotHeight
  const launch = trajectory[0]
  const landing = trajectory[trajectory.length - 1]

  return (
    <svg
      className="chart"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label="flight trajectory"
    >
      {yTicks.map((value) => (
        <g key={`y-${value}`}>
          <line
            x1={MARGIN.left}
            x2={MARGIN.left + plotWidth}
            y1={sy(value)}
            y2={sy(value)}
            className="grid"
          />
          <text x={xAxis - 8} y={sy(value)} className="tick" textAnchor="end">
            {value.toFixed(0)}
          </text>
        </g>
      ))}

      {xTicks.map((value) => (
        <g key={`x-${value}`}>
          <line
            x1={sx(value)}
            x2={sx(value)}
            y1={MARGIN.top}
            y2={MARGIN.top + plotHeight}
            className="grid"
          />
          <text x={sx(value)} y={yAxis + 14} className="tick" textAnchor="middle">
            {value.toFixed(0)}
          </text>
        </g>
      ))}

      <line
        x1={MARGIN.left}
        x2={MARGIN.left + plotWidth}
        y1={yAxis}
        y2={yAxis}
        className="axis"
      />
      <line
        x1={xAxis}
        x2={xAxis}
        y1={MARGIN.top}
        y2={MARGIN.top + plotHeight}
        className="axis"
      />

      {centralBody && (
        <circle cx={sx(0)} cy={sy(0)} r={6} className="body-point" />
      )}

      {idealRange !== null && idealRange > 0 && (
        <g>
          <line
            x1={sx(idealRange)}
            x2={sx(idealRange)}
            y1={MARGIN.top}
            y2={MARGIN.top + plotHeight}
            className="ideal-line"
          />
          <text x={sx(idealRange) - 6} y={MARGIN.top + 14} className="ideal-label" textAnchor="end">
            ideal {idealRange.toFixed(1)} m
          </text>
        </g>
      )}

      {path && <path d={path} className="trajectory" />}

      {landing && !centralBody && (
        <circle cx={sx(landing.x)} cy={sy(height(landing))} r={5} className="landing-point" />
      )}
      {launch && <circle cx={sx(launch.x)} cy={sy(height(launch))} r={5} className="launch-point" />}

      <text
        x={MARGIN.left + plotWidth / 2}
        y={HEIGHT - 10}
        className="axis-label"
        textAnchor="middle"
      >
        horizontal distance x (m)
      </text>
      <text
        x={-(MARGIN.top + plotHeight / 2)}
        y={16}
        className="axis-label"
        textAnchor="middle"
        transform="rotate(-90)"
      >
        {view === 'xz' ? 'lateral z (m)' : 'height y (m)'}
      </text>
    </svg>
  )
}
