export function StatCard({
  label,
  value,
  unit,
  delta,
  deltaLabel,
}: {
  label: string
  value: string
  unit?: string
  delta?: number
  deltaLabel?: string
}) {
  const hasDelta = delta !== undefined && Number.isFinite(delta) && delta !== 0
  const positive = (delta ?? 0) > 0
  return (
    <div className="rounded-xl border border-[var(--color-hairline)] bg-surface p-4">
      <p className="text-xs font-medium text-muted">{label}</p>
      <p className="mt-1.5 flex items-baseline gap-1">
        <span className="text-2xl font-semibold tracking-tight text-ink">{value}</span>
        {unit && <span className="text-xs text-ink2">{unit}</span>}
      </p>
      {hasDelta && (
        <p
          className="mt-1 text-xs font-medium"
          style={{
            color: positive ? 'var(--color-good)' : 'var(--color-warning)',
          }}
        >
          <span aria-hidden>{positive ? '▲' : '▼'}</span>{' '}
          {Math.abs(delta ?? 0).toLocaleString(undefined, {
            maximumFractionDigits: 0,
          })}
          % <span className="text-muted">{deltaLabel}</span>
        </p>
      )}
    </div>
  )
}
