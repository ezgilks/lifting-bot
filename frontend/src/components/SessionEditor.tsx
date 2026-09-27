import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { SessionDetail, SetDetail, Unit } from '../api'
import { api } from '../api'
import { formatDay, trim } from './chartTheme'

const INPUT =
  'w-16 rounded-md border border-[var(--color-hairline)] bg-surface-2 px-2 py-1 ' +
  'text-sm text-ink tabular outline-none focus:border-[var(--color-series-1)]'

const BUTTON =
  'rounded-md border border-[var(--color-hairline)] px-2 py-1 text-xs font-medium ' +
  'text-ink2 transition hover:bg-surface-2 disabled:opacity-40'

function useRefresh(exerciseId: number) {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: ['exercise', exerciseId] })
    void queryClient.invalidateQueries({ queryKey: ['overview'] })
    void queryClient.invalidateQueries({ queryKey: ['exercises'] })
  }
}

function SetRow({
  set,
  unit,
  exerciseId,
}: {
  set: SetDetail
  unit: Unit
  exerciseId: number
}) {
  const refresh = useRefresh(exerciseId)
  const [editing, setEditing] = useState(false)
  const [reps, setReps] = useState(String(set.reps))
  const [weight, setWeight] = useState(set.weight === null ? '' : String(set.weight))

  const save = useMutation({
    mutationFn: () => {
      const nextReps = Number(reps)
      const trimmed = weight.trim()
      return api.updateSet(set.set_id, {
        reps: Number.isFinite(nextReps) && nextReps > 0 ? nextReps : undefined,
        ...(trimmed === ''
          ? { clear_weight: true }
          : { weight: Number(trimmed) }),
      })
    },
    onSuccess: () => {
      setEditing(false)
      refresh()
    },
  })

  const remove = useMutation({
    mutationFn: () => api.deleteSet(set.set_id),
    onSuccess: refresh,
  })

  const busy = save.isPending || remove.isPending
  const error = save.error ?? remove.error

  if (!editing) {
    return (
      <li className="flex items-center gap-3 py-1.5 text-sm">
        <span className="tabular w-6 shrink-0 text-muted">{set.set_index}</span>
        <span className="tabular flex-1 text-ink2">
          {set.reps} reps
          {set.weight !== null ? ` × ${trim(set.weight)} ${unit}` : ' · bodyweight'}
          {set.is_warmup && <span className="ml-2 text-muted">warmup</span>}
        </span>
        <button type="button" className={BUTTON} onClick={() => setEditing(true)}>
          Edit
        </button>
        <button
          type="button"
          className={BUTTON}
          disabled={busy}
          onClick={() => remove.mutate()}
        >
          {remove.isPending ? '…' : 'Delete'}
        </button>
        {error && (
          <span className="text-xs" style={{ color: 'var(--color-critical)' }}>
            {error instanceof Error ? error.message : 'Failed'}
          </span>
        )}
      </li>
    )
  }

  return (
    <li className="flex flex-wrap items-center gap-2 py-1.5 text-sm">
      <span className="tabular w-6 shrink-0 text-muted">{set.set_index}</span>
      <label className="flex items-center gap-1.5 text-xs text-muted">
        reps
        <input
          className={INPUT}
          inputMode="numeric"
          value={reps}
          onChange={(e) => setReps(e.target.value)}
          aria-label={`Reps for set ${set.set_index}`}
        />
      </label>
      <label className="flex items-center gap-1.5 text-xs text-muted">
        {unit}
        <input
          className={INPUT}
          inputMode="decimal"
          value={weight}
          placeholder="BW"
          onChange={(e) => setWeight(e.target.value)}
          aria-label={`Weight for set ${set.set_index}`}
        />
      </label>
      <button
        type="button"
        className={BUTTON}
        disabled={busy}
        onClick={() => save.mutate()}
      >
        {save.isPending ? 'Saving…' : 'Save'}
      </button>
      <button
        type="button"
        className={BUTTON}
        disabled={busy}
        onClick={() => {
          setReps(String(set.reps))
          setWeight(set.weight === null ? '' : String(set.weight))
          setEditing(false)
        }}
      >
        Cancel
      </button>
      <span className="text-xs text-muted">leave weight blank for bodyweight</span>
      {error && (
        <span className="w-full text-xs" style={{ color: 'var(--color-critical)' }}>
          {error instanceof Error ? error.message : 'Failed to save'}
        </span>
      )}
    </li>
  )
}

export function SessionEditor({
  session,
  unit,
  exerciseId,
}: {
  session: SessionDetail
  unit: Unit
  exerciseId: number
}) {
  const refresh = useRefresh(exerciseId)
  const [confirming, setConfirming] = useState(false)

  const removeWorkout = useMutation({
    mutationFn: () => api.deleteWorkout(session.workout_id),
    onSuccess: refresh,
  })

  return (
    <section className="border-t border-[var(--color-hairline)] py-3 first:border-t-0">
      <header className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-ink">
            {formatDay(session.performed_on)}
          </h3>
          <p className="tabular text-xs text-muted">
            {session.hard_sets} hard set{session.hard_sets === 1 ? '' : 's'}
            {session.top_weight !== null &&
              ` · top ${trim(session.top_weight)} ${unit}${
                session.top_reps !== null ? ` × ${session.top_reps}` : ''
              }`}
          </p>
        </div>
        {confirming ? (
          <div className="flex items-center gap-2">
            <span className="text-xs text-ink2">Delete the whole session?</span>
            <button
              type="button"
              className={BUTTON}
              disabled={removeWorkout.isPending}
              onClick={() => removeWorkout.mutate()}
              style={{ color: 'var(--color-critical)' }}
            >
              {removeWorkout.isPending ? '…' : 'Yes'}
            </button>
            <button type="button" className={BUTTON} onClick={() => setConfirming(false)}>
              No
            </button>
          </div>
        ) : (
          <button type="button" className={BUTTON} onClick={() => setConfirming(true)}>
            Delete session
          </button>
        )}
      </header>

      <ul className="mt-1.5 divide-y divide-[var(--color-hairline)]">
        {session.sets.map((set) => (
          <SetRow key={set.set_id} set={set} unit={unit} exerciseId={exerciseId} />
        ))}
      </ul>

      {removeWorkout.error && (
        <p className="mt-1 text-xs" style={{ color: 'var(--color-critical)' }}>
          {removeWorkout.error instanceof Error
            ? removeWorkout.error.message
            : 'Failed to delete'}
        </p>
      )}
    </section>
  )
}
