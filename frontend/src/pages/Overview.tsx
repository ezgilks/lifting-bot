import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { HardSetsChart } from '../components/HardSetsChart'
import { MuscleGroupBars } from '../components/MuscleGroupBars'
import { StatCard } from '../components/StatCard'
import {
  Card,
  ChartSkeleton,
  EmptyState,
  ErrorState,
  Skeleton,
} from '../components/States'
import { formatDay, plural, trim } from '../components/chartTheme'

export function Overview() {
  const overview = useQuery({ queryKey: ['overview'], queryFn: api.overview })
  const exercises = useQuery({ queryKey: ['exercises'], queryFn: api.exercises })

  if (overview.isPending) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[92px]" />
          ))}
        </div>
        <Card>
          <ChartSkeleton height={260} />
        </Card>
      </div>
    )
  }

  if (overview.isError) {
    return <ErrorState error={overview.error} onRetry={() => overview.refetch()} />
  }

  const data = overview.data
  const trained = data.weekly_hard_sets.some((week) => week.total_hard_sets > 0)
  const setsDelta =
    data.total_hard_sets_last_week > 0
      ? ((data.total_hard_sets_this_week - data.total_hard_sets_last_week) /
          data.total_hard_sets_last_week) *
        100
      : undefined

  if (!trained && data.sessions_this_week === 0) {
    return (
      <EmptyState
        title="No workouts logged yet"
        hint="Send your sets to the bot — something like “bench 3x8 185” — and your charts will show up here."
      />
    )
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Hard sets this week"
          value={String(data.total_hard_sets_this_week)}
          delta={setsDelta}
          deltaLabel="vs last week"
        />
        <StatCard label="Sessions this week" value={String(data.sessions_this_week)} />
        <StatCard
          label="Current streak"
          value={String(data.current_streak_days)}
          unit={data.current_streak_days === 1 ? 'session' : 'sessions'}
        />
        <StatCard
          label="Bodyweight"
          value={data.bodyweight ? trim(data.bodyweight.weight) : '—'}
          unit={data.bodyweight ? data.bodyweight.unit : undefined}
        />
      </div>

      <Card
        title="Weekly hard sets by muscle group"
        subtitle="Working sets per ISO week — the metric this app is built around"
      >
        <HardSetsChart weeks={data.weekly_hard_sets} />
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="This week in detail" subtitle="Hard sets per muscle group">
          {data.hard_sets_this_week.length === 0 ? (
            <EmptyState title="No hard sets this week yet" />
          ) : (
            <MuscleGroupBars data={data.hard_sets_this_week} />
          )}
        </Card>

        <Card title="Stalled exercises" subtitle="Top set flat or falling over three weeks">
          {data.stalled.length === 0 ? (
            <EmptyState
              title="Nothing stalled"
              hint="Every exercise with enough recent history is still moving up."
            />
          ) : (
            <ul className="divide-y divide-[var(--color-hairline)]">
              {data.stalled.map((item) => (
                <li key={item.exercise_id}>
                  <Link
                    to={`/exercise/${item.exercise_id}`}
                    className="flex items-center justify-between py-2.5 text-sm transition hover:text-ink"
                  >
                    <span className="text-ink2">{item.name}</span>
                    <span
                      className="tabular text-xs"
                      style={{ color: 'var(--color-warning)' }}
                    >
                      {trim(item.slope_per_week)} {data.unit}/wk
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="Exercises" subtitle="Sorted by most recently trained — click to edit sets">
        {exercises.isPending && <Skeleton className="h-40 w-full" />}
        {exercises.isError && (
          <ErrorState error={exercises.error} onRetry={() => exercises.refetch()} />
        )}
        {exercises.data && exercises.data.length === 0 && (
          <EmptyState title="No exercises logged yet" />
        )}
        {exercises.data && exercises.data.length > 0 && (
          <ul className="divide-y divide-[var(--color-hairline)]">
            {exercises.data.map((item) => (
              <li key={item.id}>
                <Link
                  to={`/exercise/${item.id}`}
                  className="flex items-center justify-between gap-3 py-2.5 text-sm transition hover:text-ink"
                >
                  <span className="truncate text-ink2">{item.name}</span>
                  <span className="tabular shrink-0 text-xs text-muted">
                    {plural(item.hard_sets, 'set')} ·{' '}
                    {plural(item.session_count, 'session')}
                    {item.top_weight !== null &&
                      ` · top ${trim(item.top_weight)} ${data.unit}`}
                    {item.last_trained_on && ` · ${formatDay(item.last_trained_on)}`}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
