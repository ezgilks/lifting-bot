import { useQuery } from '@tanstack/react-query'
import { Link, Route, Routes } from 'react-router-dom'
import { api, getToken } from './api'
import { ExerciseDetail } from './pages/ExerciseDetail'
import { Overview } from './pages/Overview'

function ParserBadge() {
  const stats = useQuery({ queryKey: ['parser-stats'], queryFn: api.parserStats })
  if (!stats.data || stats.data.rules_hits + stats.data.llm_hits === 0) return null
  return (
    <span className="tabular text-xs text-muted">
      {Math.round(stats.data.rules_share * 100)}% parsed without the LLM
    </span>
  )
}

function NoToken() {
  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="max-w-sm text-center">
        <h1 className="text-lg font-semibold text-ink">No dashboard link</h1>
        <p className="mt-2 text-sm text-ink2">
          Send{' '}
          <code className="rounded bg-surface-2 px-1.5 py-0.5 text-xs">/dashboard</code>{' '}
          to the bot on Telegram and open the link it replies with.
        </p>
        <p className="mt-2 text-xs text-muted">Links stay valid for 24 hours.</p>
      </div>
    </div>
  )
}

export function App() {
  if (!getToken()) return <NoToken />

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-[var(--color-hairline)] bg-plane/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <Link to="/" className="text-sm font-semibold tracking-tight text-ink">
            Lifting Dashboard
          </Link>
          <ParserBadge />
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-5">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/exercise/:id" element={<ExerciseDetail />} />
          <Route path="*" element={<Overview />} />
        </Routes>
      </main>
    </div>
  )
}
