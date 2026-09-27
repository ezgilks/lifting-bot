import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from 'recharts'
import type { MuscleGroupSets } from '../api'
import { MUSCLE_LABEL, SERIES, chrome } from './chartTheme'

/**
 * One series, so magnitude carries the meaning and a single hue is correct —
 * no legend, and every bar is directly labeled.
 */
export function MuscleGroupBars({ data }: { data: MuscleGroupSets[] }) {
  const rows = data.map((item) => ({
    label: MUSCLE_LABEL[item.muscle_group],
    sets: item.hard_sets,
  }))

  return (
    <ResponsiveContainer width="100%" height={Math.max(140, rows.length * 30)}>
      <BarChart
        data={rows}
        layout="vertical"
        margin={{ top: 0, right: 28, bottom: 0, left: 0 }}
      >
        <CartesianGrid horizontal={false} stroke={chrome.grid} />
        <XAxis type="number" hide allowDecimals={false} />
        <YAxis
          type="category"
          dataKey="label"
          tick={{ fill: chrome.ink2, fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          width={92}
        />
        <Bar
          isAnimationActive={false}
          dataKey="sets"
          fill={SERIES[0]}
          radius={[0, 4, 4, 0]}
          maxBarSize={18}
        >
          <LabelList
            dataKey="sets"
            position="right"
            className="tabular"
            fill={chrome.ink2}
            fontSize={11}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
