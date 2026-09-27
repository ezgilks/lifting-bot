import type { MuscleGroup } from '../api'

/**
 * Chart chrome and the categorical palette.
 *
 * The seven series hexes are a validated fixed-order palette for this dark
 * surface. Slots are assigned per entity below and never reordered by rank,
 * so a quiet week never repaints the other series.
 */
export const chrome = {
  surface: '#141413',
  grid: '#2c2c2a',
  axis: '#383835',
  muted: '#898781',
  ink: '#ffffff',
  ink2: '#c3c2b7',
} as const

export const SERIES = [
  '#3987e5',
  '#d95926',
  '#199e70',
  '#c98500',
  '#d55181',
  '#008300',
  '#9085e9',
] as const

export const MUSCLE_LABEL: Record<MuscleGroup, string> = {
  chest: 'Chest',
  back: 'Back',
  quads: 'Quads',
  hamstrings: 'Hamstrings',
  glutes: 'Glutes',
  shoulders: 'Shoulders',
  biceps: 'Biceps',
  triceps: 'Triceps',
  calves: 'Calves',
  core: 'Core',
  full_body: 'Full body',
}

/**
 * Eleven muscle groups is more series than any stack can stay readable at, so
 * the weekly stack rolls them into seven fixed regions. The per-week detail
 * chart still shows every group individually, in a single hue.
 */
export const REGIONS = [
  { key: 'chest', label: 'Chest', color: SERIES[0], groups: ['chest'] },
  { key: 'back', label: 'Back', color: SERIES[1], groups: ['back'] },
  {
    key: 'legs',
    label: 'Legs',
    color: SERIES[2],
    groups: ['quads', 'hamstrings', 'glutes', 'calves'],
  },
  { key: 'shoulders', label: 'Shoulders', color: SERIES[3], groups: ['shoulders'] },
  { key: 'arms', label: 'Arms', color: SERIES[4], groups: ['biceps', 'triceps'] },
  { key: 'core', label: 'Core', color: SERIES[5], groups: ['core'] },
  { key: 'full_body', label: 'Full body', color: SERIES[6], groups: ['full_body'] },
] as const satisfies ReadonlyArray<{
  key: string
  label: string
  color: string
  groups: ReadonlyArray<MuscleGroup>
}>

export function formatWeekLabel(isoDate: string): string {
  const date = new Date(`${isoDate}T00:00:00`)
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function formatDay(isoDate: string): string {
  const date = new Date(`${isoDate}T00:00:00`)
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function compact(value: number): string {
  if (Math.abs(value) >= 10000) return `${(value / 1000).toFixed(1)}k`
  return value.toLocaleString(undefined, { maximumFractionDigits: 0 })
}

/** "1 set" / "2 sets" -- a count with its correctly pluralised noun. */
export function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}

export function trim(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 1 })
}
