import type { CSSProperties, ReactNode } from 'react'

export function Card({
  title,
  subtitle,
  children,
  className = '',
}: {
  title?: string
  subtitle?: string
  children: ReactNode
  className?: string
}) {
  return (
    <section
      className={`rounded-xl border border-[var(--color-hairline)] bg-surface p-4 ${className}`}
    >
      {title && (
        <header className="mb-3">
          <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
        </header>
      )}
      {children}
    </section>
  )
}

export function Skeleton({
  className = '',
  style,
}: {
  className?: string
  style?: CSSProperties
}) {
  return <div className={`skeleton rounded-md ${className}`} style={style} />
}

export function ChartSkeleton({ height = 240 }: { height?: number }) {
  return (
    <div className="space-y-3">
      <Skeleton className="h-3 w-32" />
      <Skeleton style={{ height }} className="w-full" />
    </div>
  )
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-[var(--color-hairline)] px-6 py-10 text-center">
      <p className="text-sm font-medium text-ink2">{title}</p>
      {hint && <p className="max-w-sm text-xs text-muted">{hint}</p>}
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message =
    error instanceof Error ? error.message : 'Something went wrong loading this view.'
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-[var(--color-critical)]/40 bg-[var(--color-critical)]/5 px-6 py-8 text-center">
      <p className="text-sm font-medium text-ink">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md border border-[var(--color-hairline)] px-3 py-1.5 text-xs font-medium text-ink2 transition hover:bg-surface-2"
        >
          Try again
        </button>
      )}
    </div>
  )
}

export function Legend({
  items,
}: {
  items: ReadonlyArray<{ label: string; color: string; dashed?: boolean }>
}) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5 text-xs text-ink2">
          <span
            aria-hidden
            className="inline-block h-0.5 w-3.5 rounded-full"
            style={{
              backgroundColor: item.dashed ? 'transparent' : item.color,
              borderTop: item.dashed ? `2px dashed ${item.color}` : undefined,
            }}
          />
          {item.label}
        </li>
      ))}
    </ul>
  )
}

export function TooltipShell({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-[var(--color-hairline)] bg-surface-2 px-3 py-2 text-xs shadow-lg">
      {children}
    </div>
  )
}
