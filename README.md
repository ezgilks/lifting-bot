# Lifting Bot

Log your lifting from Telegram in whatever shorthand you already use, and get
progression analytics back — weekly hard sets per muscle group, top-set trends,
stall detection, and a concrete target for your next session.

Volume is measured in **sets, not pounds lifted**, and every number reported is
a weight actually moved: there are no estimated 1RMs anywhere.

```
you   bench 3x8 185
bot   ✅ Logged · Thu Aug 13
      Barbell Bench Press — 3x8 @ 185 lb
      3 hard sets this session
```

That message never touches an LLM. Only phrasing the regex parser refuses —
*"did about five sets of eight on incline dumbbell press with the 60s"* — falls
through to Groq.

---

## What it does

**Telegram bot**

| Command | |
|---|---|
| *(any plain message)* | logged as a workout |
| `/start` | create your account, pick lb or kg |
| `/today` | everything logged today, grouped by exercise, with hard-set count |
| `/last <exercise>` | last 3 sessions with set detail and your next target |
| `/week` | sessions and hard sets per muscle group, week-over-week delta |
| `/next` | targets for everything trained in the last 10 days |
| `/bw 187` | log bodyweight |
| `/undo` | pick any of your last 5 workouts to delete |
| `/fix <shorthand>` | replace your most recent workout with a corrected one |
| `/dashboard` | a 24-hour magic link to your charts |
| `/help` | commands plus every supported input format |

**Dashboard** — weekly hard sets by muscle group over the trailing 12 weeks,
streak and session counts, bodyweight, and stalled exercises; per exercise, a
top-set chart with the fitted trend line overlaid, the next-session
recommendation, and an editable session history where any set can be corrected
or deleted.

## Architecture

One FastAPI process does everything: it serves the REST API, serves the built
React app as static files, and runs the Telegram polling loop as an asyncio task
started in the lifespan handler. One container, one deploy.

```
Telegram ──polling──┐
                    ▼
              app/bot/handlers.py
                    │
                    ▼
          app/parsing/pipeline.py
                    │
   ┌────────────────┴─────────────────┐
   │  Tier 1  rules.py                │  regex. no API call.
   │          ~all real messages       │  returns None unless certain
   └────────────────┬─────────────────┘
                    │ None
   ┌────────────────▼─────────────────┐
   │  Tier 2  llm.py                  │  Groq, temperature 0, JSON mode
   │          only the awkward ones    │  validate → retry once → give up
   └────────────────┬─────────────────┘
                    │
   ┌────────────────▼─────────────────┐
   │  Tier 3  resolver.py             │  exact → alias → fuzzy ≥ 88
   │          name → catalog row       │  below that, ask with buttons
   └────────────────┬─────────────────┘
                    ▼
            app/queries.py  ──►  Postgres
                    │
   ┌────────────────▼─────────────────┐
   │  app/analytics/  pure functions   │  hard sets · top set · trends
   └────────────────┬─────────────────┘
                    ▼
        app/api/routes.py  ──►  React dashboard
```

**Why the tiers are ordered this way.** Tier 1 is strict on purpose: a segment
either matches a known shape or the whole message is rejected. Partial
confidence is failure, because a wrong silent guess is worse than one extra API
call. `GET /api/stats/parser` reports the rules-vs-LLM split so you can see how
often Tier 2 is actually needed.

**Analytics** (`app/analytics/`) are pure functions over dataclasses with no I/O,
which is why they are cheap to test exhaustively:

- **Hard sets** — working sets per muscle group per ISO week. Warmups never
  count. This is the primary metric, on the bot and the dashboard alike.
- **Top set** — the heaviest working set of a session, ties broken on reps.
  Bodyweight-only sessions rank by reps instead.
- **Trend** — OLS of top-set weight against days, reported per week, for
  exercises with ≥ 4 sessions in the trailing 8 weeks.
- **Stall** — slope ≤ 0 across the trailing 3 weeks with ≥ 3 sessions there.
- **Next target** — double progression. All sets at the top of your inferred rep
  range → add weight (5 lb barbell lower body, 2.5 lb otherwise; 2.5 / 1.25 kg)
  and restart at the bottom of the range. Otherwise same weight, one more rep on
  the first set that fell short. Stalled → 10% deload, and it says why.

## Local setup

### With Docker (recommended)

```bash
cp .env.example .env      # fill in TELEGRAM_BOT_TOKEN, GROQ_API_KEY, APP_SECRET
docker compose up --build
```

That starts Postgres 16, creates the tables, seeds the exercise catalog, and
begins polling. The dashboard is at http://localhost:8000 — but open it via the
link `/dashboard` sends you, since every endpoint needs the token.

`APP_SECRET` must be at least 32 characters; the app refuses to start otherwise:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Without Docker

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                    # point DATABASE_URL at your Postgres
uvicorn app.main:app --reload           # API + bot on :8000

cd frontend && npm install
npm run dev                             # dashboard on :5173, proxies /api to :8000
```

In dev the Vite server serves the frontend. The FastAPI app only serves static
files when `frontend/dist` exists — run `npm run build` to have it do so.

### Tests

```bash
pytest
```

140 tests, no Postgres, no Telegram, no Groq key. The database is in-memory
SQLite and the Groq client is mocked.

## Opening the dashboard

Three ways in, all issuing the same 24-hour signed link:

**From Telegram** — send `/dashboard`. The link points at `PUBLIC_BASE_URL`, so
it only opens on devices that can reach that address.

**From the Mac, without Telegram** — mints a link and opens your browser:

```bash
.venv/bin/python scripts/open_dashboard.py           # opens it
.venv/bin/python scripts/open_dashboard.py --print   # just prints the URL
```

Worth an alias in `~/.zshrc`:

```bash
alias lifting-dash='(cd ~/lifting-bot && .venv/bin/python scripts/open_dashboard.py)'
```

**From your phone, against a local machine.** `localhost` on your phone means
your phone, so a local `PUBLIC_BASE_URL` will not open there. Put a tunnel in
front of the app and point `PUBLIC_BASE_URL` at it:

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8000     # prints https://<random>.trycloudflare.com
```

Set `PUBLIC_BASE_URL` to that URL, restart the app, and `/dashboard` links open
anywhere. Two caveats: the quick-tunnel URL changes every time cloudflared
restarts, so `.env` needs updating each time, and the tunnel must stay running.
The API still demands a bearer token, so the public URL alone exposes nothing —
visitors without a link get the "No dashboard link" page. For anything permanent,
deploy to Railway and set `PUBLIC_BASE_URL` to the Railway domain instead.

## Editing entries

Parsing is not perfect, so corrections are first-class in both places.

**Dashboard** — open any exercise. Each set in the session history has *Edit*
(change reps or weight; leave the weight blank to make it a bodyweight set) and
*Delete*. Each session has *Delete session*. Deleting the last set of a session
removes the session too, and remaining sets are renumbered.

**Telegram** — `/undo` lists your last 5 workouts as buttons so you can remove
any of them, not just the newest. `/fix hack squat 200x6` replaces your most
recent workout with a corrected one, keeping the original date.

Every write endpoint re-checks ownership against the token's user, so a set id
belonging to someone else returns 404 rather than being edited.

| Endpoint | |
|---|---|
| `PATCH /api/sets/{id}` | change reps, weight, RPE, or warmup flag |
| `DELETE /api/sets/{id}` | remove one set |
| `DELETE /api/workouts/{id}` | remove a whole session |

## Getting the credentials

**Telegram bot token** — message [@BotFather](https://t.me/BotFather) on
Telegram, send `/newbot`, pick a display name and a username ending in `bot`.
It replies with a token like `8012345678:AAH...`. That is
`TELEGRAM_BOT_TOKEN`.

**Groq API key** — sign in at [console.groq.com](https://console.groq.com),
open *API Keys*, *Create API Key*. That is `GROQ_API_KEY`. The default
`GROQ_MODEL` is `llama-3.3-70b-versatile`; any Groq model that supports JSON
mode works, and the model id is only ever read from this variable.

## Deploying to Railway

1. Push this repo to GitHub.
2. In Railway, **New Project → Deploy from GitHub repo**. `railway.json` selects
   the Dockerfile build and the `/healthz` health check.
3. **New → Database → PostgreSQL** in the same project. Railway injects
   `DATABASE_URL`; the app rewrites its `postgresql://` scheme to
   `postgresql+asyncpg://` automatically.
4. Set the remaining variables on the app service: `TELEGRAM_BOT_TOKEN`,
   `GROQ_API_KEY`, `APP_SECRET`, and `GROQ_MODEL` if you want a different model.
5. Generate a public domain, then set `PUBLIC_BASE_URL` to it
   (e.g. `https://lifting-bot-production.up.railway.app`) so `/dashboard` hands
   out reachable links. Redeploy after setting it.

**Keep this at one replica.** Telegram allows a single active poller per token;
a second instance will fight the first for updates. `railway.json` pins
`numReplicas: 1`.

## Environment variables

| Variable | Required | |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | from BotFather |
| `GROQ_API_KEY` | yes | from the Groq console |
| `GROQ_MODEL` | no | defaults to `llama-3.3-70b-versatile` |
| `DATABASE_URL` | yes | `postgresql+asyncpg://…`; bare `postgresql://` is upgraded |
| `APP_SECRET` | yes | ≥ 32 chars, signs dashboard links |
| `PUBLIC_BASE_URL` | no | defaults to `http://localhost:8000` |
| `LOG_LEVEL` | no | defaults to `INFO` |

Missing or too-short values raise at startup rather than degrading quietly.

## Input formats

```
bench 3x8 185                    sets × reps, then weight
squat 225 5x3                    weight, then sets × reps
ohp 95x5, 95x5, 100x4            explicit per-set entries
deadlift 315x5 @8                trailing RPE (also `rpe 8`)
curls 3x12 30lb                  explicit unit (lb / lbs / kg / kgs / #)
pullups 3x8                      bodyweight
bench 185 5,5,4                  weight, then a rep list
pullups 8,7,6                    bodyweight rep list
warmup bench 135x5               marked as a warmup, excluded from analytics
```

Combine exercises with newlines, `;`, ` / `, or a comma followed by a name:

```
bench 3x8 185 / squat 5x5 225
curls 3x12 30lb, hammer curls 3x10 25lb
```

A bare `AxB` is read as sets × reps when A ≤ 10 and as a weight above that, so
`3x8` is three sets of eight and `315x5` is 315 for five. Two or more
comma-separated `AxB` entries are always weight × reps. Anything the parser
cannot place with certainty goes to the LLM instead of being guessed at.
