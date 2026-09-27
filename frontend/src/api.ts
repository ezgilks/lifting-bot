/** Typed client for the dashboard API, plus magic-link token handling. */

const TOKEN_KEY = 'lifting-bot-token'

let memoryToken: string | null = null

export function initToken(): string | null {
  const fromQuery = new URLSearchParams(window.location.search).get('t')
  if (fromQuery) {
    memoryToken = fromQuery
    sessionStorage.setItem(TOKEN_KEY, fromQuery)
    // Drop the token from the address bar so it does not linger in history.
    const url = new URL(window.location.href)
    url.searchParams.delete('t')
    window.history.replaceState({}, '', url.pathname + url.search + url.hash)
    return fromQuery
  }
  memoryToken = memoryToken ?? sessionStorage.getItem(TOKEN_KEY)
  return memoryToken
}

export function getToken(): string | null {
  return memoryToken ?? sessionStorage.getItem(TOKEN_KEY)
}

export function clearToken(): void {
  memoryToken = null
  sessionStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(
  path: string,
  init: { method?: string; body?: unknown } = {},
): Promise<T> {
  const token = getToken()
  if (!token) {
    throw new ApiError('No dashboard link found. Send /dashboard to the bot.', 401)
  }
  const response = await fetch(`/api${path}`, {
    method: init.method ?? 'GET',
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init.body === undefined ? {} : { 'Content-Type': 'application/json' }),
    },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  })
  if (!response.ok) {
    if (response.status === 401) clearToken()
    let detail = `Request failed (${response.status})`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) detail = 'That value is not allowed.'
    } catch {
      // Non-JSON error body; the status-based message stands.
    }
    throw new ApiError(detail, response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export type Unit = 'lb' | 'kg'

export type MuscleGroup =
  | 'chest'
  | 'back'
  | 'quads'
  | 'hamstrings'
  | 'glutes'
  | 'shoulders'
  | 'biceps'
  | 'triceps'
  | 'calves'
  | 'core'
  | 'full_body'

export interface MuscleGroupSets {
  muscle_group: MuscleGroup
  hard_sets: number
}

export interface WeekPoint {
  iso_week: string
  week_start: string
  sessions: number
  hard_sets: Partial<Record<MuscleGroup, number>>
  total_hard_sets: number
}

export interface StalledExercise {
  exercise_id: number
  name: string
  slope_per_week: number
  sessions: number
}

export interface BodyweightPoint {
  weight: number
  unit: Unit
  recorded_on: string
}

export interface Overview {
  unit: Unit
  sessions_this_week: number
  hard_sets_this_week: MuscleGroupSets[]
  total_hard_sets_this_week: number
  total_hard_sets_last_week: number
  weekly_hard_sets: WeekPoint[]
  current_streak_days: number
  stalled: StalledExercise[]
  bodyweight: BodyweightPoint | null
}

export interface ExerciseSummary {
  id: number
  name: string
  muscle_group: MuscleGroup
  equipment: string
  session_count: number
  hard_sets: number
  last_trained_on: string | null
  top_weight: number | null
}

export interface SetDetail {
  set_id: number
  set_index: number
  reps: number
  weight: number | null
  unit: Unit
  rpe: number | null
  is_warmup: boolean
}

export interface SessionDetail {
  workout_id: number
  performed_on: string
  sets: SetDetail[]
  hard_sets: number
  top_weight: number | null
  top_reps: number | null
}

export interface SeriesPoint {
  performed_on: string
  value: number
  reps: number | null
}

export interface TrendInfo {
  slope_per_week: number | null
  intercept: number | null
  sessions: number
  is_stalled: boolean
  first_session_on: string | null
}

export interface NextTarget {
  kind: 'increase' | 'repeat' | 'deload'
  weight: number | null
  unit: Unit
  target_reps: number
  sets: number
  reason: string
}

export interface ExerciseDetail {
  id: number
  name: string
  muscle_group: MuscleGroup
  equipment: string
  unit: Unit
  sessions: SessionDetail[]
  top_weight_series: SeriesPoint[]
  trend: TrendInfo
  next_target: NextTarget | null
}

export interface SetUpdate {
  reps?: number
  weight?: number
  rpe?: number
  is_warmup?: boolean
  clear_weight?: boolean
  clear_rpe?: boolean
}

export interface ParserStats {
  rules_hits: number
  llm_hits: number
  rules_share: number
  process_rules_hits: number
  process_llm_hits: number
  process_llm_failures: number
}

export const api = {
  overview: () => request<Overview>('/overview'),
  exercises: () => request<ExerciseSummary[]>('/exercises'),
  exercise: (id: number) => request<ExerciseDetail>(`/exercises/${id}`),
  parserStats: () => request<ParserStats>('/stats/parser'),

  updateSet: (setId: number, body: SetUpdate) =>
    request<SetDetail>(`/sets/${setId}`, { method: 'PATCH', body }),
  deleteSet: (setId: number) =>
    request<void>(`/sets/${setId}`, { method: 'DELETE' }),
  deleteWorkout: (workoutId: number) =>
    request<void>(`/workouts/${workoutId}`, { method: 'DELETE' }),
}
