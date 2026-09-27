import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { WeekPoint } from '../api'
import { Legend, TooltipShell } from './States'
import { REGIONS, chrome, formatWeekLabel } from './chartTheme'

interface Row {
  week: string
  label: string
  total: number
  [region: string]: string | number
}

function toRows(weeks: WeekPoint[]): Row[] {
  return weeks.map((week) => {
    const row: Row = {
      week: week.iso_week,
      label: formatWeekLabel(week.week_start),
      total: 0,
    }
    for (const region of REGIONS) {
      const count = region.groups.reduce(
        (sum, group) => sum + (week.hard_sets[group] ?? 0),
        0,
      )
      row[region.key] = count
      row.total += count
    }
    return row
  })
}

function HardSetsTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: Array<{ payload: Row }>
  label?: string
}) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  const present = REGIONS.filter((region) => (row[region.key] as number) > 0)
  return (
    <TooltipShell>
      <p className="mb-1.5 font-medium text-ink">Week of {label}</p>
      {present.length === 0 ? (
        <p className="text-muted">No hard sets</p>
      ) : (
        <ul className="space-y-0.5">
          {present.map((region) => (
            <li key={region.key} className="flex items-center gap-2">
              <span
                aria-hidden
                className="h-2 w-2 shrink-0 rounded-sm"
                style={{ backgroundColor: region.color }}
              />
              <span className="text-ink2">{region.label}</span>
              <span className="tabular ml-auto pl-3 text-ink">{row[region.key]}</span>
            </li>
          ))}
          <li className="mt-1 flex items-center gap-2 border-t border-[var(--color-hairline)] pt-1">
            <span className="text-muted">Total</span>
            <span className="tabular ml-auto pl-3 font-medium text-ink">{row.total}</span>
          </li>
        </ul>
      )}
    </TooltipShell>
  )
}

export function HardSetsChart({ weeks }: { weeks: WeekPoint[] }) {
  const rows = toRows(weeks)
  const lastIndex = REGIONS.length - 1
  // Legend covers what is actually on screen. Colors stay bound to the region,
  // so a region appearing later never repaints the others.
  const trained = REGIONS.filter((region) =>
    rows.some((row) => (row[region.key] as number) > 0),
  )

  return (
    <div>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
          <CartesianGrid vertical={false} stroke={chrome.grid} />
          <XAxis
            dataKey="label"
            tick={{ fill: chrome.muted, fontSize: 11 }}
            axisLine={{ stroke: chrome.axis }}
            tickLine={false}
            interval="preserveStartEnd"
            minTickGap={12}
          />
          <YAxis
            tick={{ fill: chrome.muted, fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={44}
            allowDecimals={false}
          />
          <Tooltip
            cursor={{ fill: 'rgba(255,255,255,0.04)' }}
            content={<HardSetsTooltip />}
          />
          {REGIONS.map((region, index) => (
            <Bar
              isAnimationActive={false}
              key={region.key}
              dataKey={region.key}
              name={region.label}
              stackId="sets"
              fill={region.color}
              stroke={chrome.surface}
              strokeWidth={2}
              radius={index === lastIndex ? [4, 4, 0, 0] : undefined}
              maxBarSize={44}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
      <div className="mt-3">
        <Legend items={trained.map((r) => ({ label: r.label, color: r.color }))} />
      </div>
    </div>
  )
}
