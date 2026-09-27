import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { SeriesPoint, TrendInfo, Unit } from '../api'
import { Legend, TooltipShell } from './States'
import { SERIES, chrome, formatDay, trim } from './chartTheme'

interface Row {
  label: string
  weight: number
  reps: number | null
  trend: number | null
}

/** Evaluate the fitted OLS line at each session date, in the same units. */
function withTrend(points: SeriesPoint[], trend: TrendInfo): Row[] {
  const canFit =
    trend.slope_per_week !== null &&
    trend.intercept !== null &&
    trend.first_session_on !== null
  const origin = canFit ? new Date(`${trend.first_session_on}T00:00:00`).getTime() : 0
  const perDay = canFit ? (trend.slope_per_week as number) / 7 : 0

  return points.map((point) => {
    const at = new Date(`${point.performed_on}T00:00:00`).getTime()
    const days = (at - origin) / 86_400_000
    return {
      label: formatDay(point.performed_on),
      weight: point.value,
      reps: point.reps,
      trend: canFit && days >= 0 ? (trend.intercept as number) + perDay * days : null,
    }
  })
}

function TopWeightTooltip({
  active,
  payload,
  label,
  unit,
}: {
  active?: boolean
  payload?: Array<{ payload: Row }>
  label?: string
  unit: Unit
}) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  return (
    <TooltipShell>
      <p className="mb-1 font-medium text-ink">{label}</p>
      <p className="tabular text-ink2">
        Top set {trim(row.weight)} {unit}
        {row.reps !== null && ` × ${row.reps}`}
      </p>
      {row.trend !== null && (
        <p className="tabular text-muted">
          Trend {trim(row.trend)} {unit}
        </p>
      )}
    </TooltipShell>
  )
}

/** Heaviest working set per session, with the fitted trend overlaid. */
export function TopWeightChart({
  points,
  trend,
  unit,
}: {
  points: SeriesPoint[]
  trend: TrendInfo
  unit: Unit
}) {
  const rows = withTrend(points, trend)
  const hasTrend = rows.some((row) => row.trend !== null)

  return (
    <div>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid vertical={false} stroke={chrome.grid} />
          <XAxis
            dataKey="label"
            tick={{ fill: chrome.muted, fontSize: 11 }}
            axisLine={{ stroke: chrome.axis }}
            tickLine={false}
            interval="preserveStartEnd"
            minTickGap={16}
          />
          <YAxis
            tick={{ fill: chrome.muted, fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={48}
            domain={['auto', 'auto']}
          />
          <Tooltip
            cursor={{ stroke: chrome.axis, strokeWidth: 1 }}
            content={<TopWeightTooltip unit={unit} />}
          />
          <Line
            isAnimationActive={false}
            type="monotone"
            dataKey="weight"
            name="Top set"
            stroke={SERIES[0]}
            strokeWidth={2}
            dot={{ r: 3, fill: SERIES[0], stroke: chrome.surface, strokeWidth: 2 }}
            activeDot={{ r: 5, stroke: chrome.surface, strokeWidth: 2 }}
          />
          {hasTrend && (
            <Line
              isAnimationActive={false}
              type="linear"
              dataKey="trend"
              name="Trend"
              stroke={SERIES[1]}
              strokeWidth={2}
              strokeDasharray="5 4"
              dot={false}
              activeDot={false}
              connectNulls
            />
          )}
        </LineChart>
      </ResponsiveContainer>
      {hasTrend && (
        <div className="mt-3">
          <Legend
            items={[
              { label: `Top set (${unit})`, color: SERIES[0] },
              { label: '8-week trend', color: SERIES[1], dashed: true },
            ]}
          />
        </div>
      )}
    </div>
  )
}
