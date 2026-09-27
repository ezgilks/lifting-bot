import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import type { NextTarget } from '../api'
import { SessionEditor } from '../components/SessionEditor'
import { TopWeightChart } from '../components/TopWeightChart'
import {
  Card,
  ChartSkeleton,
  EmptyState,
  ErrorState,
  Skeleton,
} from '../components/States'
import { MUSCLE_LABEL, plural, trim } from '../components/chartTheme'

const TARGET_STYLE: Record<
  NextTarget['kind'],
  { icon: string; color: string; title: string }
> = {
  increase: { icon: '▲', color: 'var(--color-good)', title: 'Add weight' },
  repeat: { icon: '▪', color: 'var(--color-series-1)', title: 'Same weight, more reps' },
  deload: { icon: '▼', color: 'var(--color-warning)', title: 'Deload' },
}

export function ExerciseDetail() {
  const { id } = useParams<{ id: string }>()
  const exerciseId = Number(id)
  const query = useQuery({
    queryKey: ['exercise', exerciseId],
    queryFn: () => api.exercise(exerciseId),
    enabled: Number.isFinite(exerciseId),
  })

  if (query.isPending) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-56" />
        <Card>
          <ChartSkeleton height={260} />
        </Card>
      </div>
    )
  }

  if (query.isError) {
    return (
      <div className="space-y-3">
        <Link to="/" className="text-xs text-muted transition hover:text-ink2">
          ← Overview
        </Link>
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      </div>
    )
  }

  const data = query.data
  const target = data.next_target
  const style = target ? TARGET_STYLE[target.kind] : null
  const totalHardSets = data.sessions.reduce((sum, s) => sum + s.hard_sets, 0)

  return (
    <div className="space-y-4">
      <div>
        <Link to="/" className="text-xs text-muted transition hover:text-ink2">
          ← Overview
        </Link>
        <h1 className="mt-1 text-xl font-semibold tracking-tight text-ink">
          {data.name}
        </h1>
        <p className="text-xs text-muted">
          {MUSCLE_LABEL[data.muscle_group]} · {data.equipment} ·{' '}
          {plural(totalHardSets, 'hard set')} across{' '}
          {plural(data.sessions.length, 'session')}
          {data.trend.slope_per_week !== null &&
            ` · ${data.trend.slope_per_week > 0 ? '+' : ''}${trim(
              data.trend.slope_per_week,
            )} ${data.unit}/wk`}
        </p>
      </div>

      {target && style && (
        <section
          className="rounded-xl border border-[var(--color-hairline)] bg-surface p-4"
          style={{ borderLeft: `3px solid ${style.color}` }}
        >
          <p
            className="flex items-center gap-2 text-xs font-medium"
            style={{ color: style.color }}
          >
            <span aria-hidden>{style.icon}</span>
            {style.title}
          </p>
          <p className="tabular mt-1.5 text-lg font-semibold text-ink">
            {target.sets} × {target.target_reps}
            {target.weight !== null
              ? ` @ ${trim(target.weight)} ${target.unit}`
              : ' bodyweight'}
          </p>
          <p className="mt-1 text-xs text-ink2">{target.reason}</p>
        </section>
      )}

      <Card
        title="Top set"
        subtitle={
          data.trend.is_stalled
            ? 'Stalled — flat or falling over the last three weeks'
            : `Heaviest working set per session, ${data.unit}`
        }
      >
        {data.top_weight_series.length === 0 ? (
          <EmptyState
            title="No loaded sets yet"
            hint="Bodyweight-only sessions have no weight to chart."
          />
        ) : data.top_weight_series.length === 1 ? (
          <div className="py-4">
            <p className="tabular text-2xl font-semibold text-ink">
              {trim(data.top_weight_series[0].value)} {data.unit}
              {data.top_weight_series[0].reps !== null && (
                <span className="text-base text-ink2">
                  {' '}
                  × {data.top_weight_series[0].reps}
                </span>
              )}
            </p>
            <p className="mt-1 text-xs text-muted">
              One session so far — log this lift again and a trend line appears here.
            </p>
          </div>
        ) : (
          <TopWeightChart
            points={data.top_weight_series}
            trend={data.trend}
            unit={data.unit}
          />
        )}
      </Card>

      <Card
        title="Session history"
        subtitle="Most recent first — edit a set if it did not go through correctly"
      >
        <div>
          {[...data.sessions].reverse().map((session) => (
            <SessionEditor
              key={session.workout_id}
              session={session}
              unit={data.unit}
              exerciseId={data.id}
            />
          ))}
        </div>
      </Card>
    </div>
  )
}
