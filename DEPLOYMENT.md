# Deployment Guide — BayitPro

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Option A (recommended for demo)          Option B (future)     │
│                                                                  │
│  Render (web service)                 Vercel  ──►  Render       │
│  ├── FastAPI backend                  (static)     (API only)   │
│  ├── Static HTML/JS/CSS                                         │
│  └── WebSocket (/ws)                                            │
│                                                                  │
│  Supabase ─── PostgreSQL (both options)                         │
└─────────────────────────────────────────────────────────────────┘
```

**For this demo, use Option A (Render full-stack).** Option B (Vercel + Render split) is documented below but requires replacing `RENDER_BACKEND_URL` in `vercel.json` and has a WebSocket limitation (Vercel does not proxy WebSocket connections — live ticket notifications won't work through Vercel).

---

## Prerequisites

- GitHub repo connected to Render and Vercel
- Supabase account (free tier)
- Twilio account with a WhatsApp sandbox or verified number
- Anthropic API key

---

## Step 1 — Supabase (Database)

1. Go to [supabase.com](https://supabase.com) → **New project**
2. Choose a region close to your Render region (e.g. Frankfurt)
3. After the project is created, go to **Settings → Database**
4. Copy the **Connection string** → **URI** tab
   - It looks like: `postgresql://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres`
5. Save this as `DATABASE_URL` — you'll paste it into Render in the next step

### Run migrations against Supabase

```bash
# From your local machine with .env configured:
DATABASE_URL="postgresql://postgres:..." alembic upgrade head
```

This creates all tables. Run once per fresh database.

---

## Step 2 — Render (Backend + Frontend)

### 2a. Create the service

1. Go to [render.com](https://render.com) → **New → Web Service**
2. Connect your GitHub repo
3. Render will detect `render.yaml` automatically — click **Apply**
4. This creates one resource: `bayitpro-backend` web service (Python, free plan)

> Render does **not** create a database. The database is Supabase — set `DATABASE_URL` manually in step 2b.

### 2b. Set environment variables

In the Render dashboard → **bayitpro-backend** → **Environment**:

| Variable | Value | Notes |
|----------|-------|-------|
| `ENV` | `production` | Auto-set by render.yaml |
| `DATABASE_URL` | `postgresql://postgres:[PW]@db.[REF].supabase.co:5432/postgres` | Paste the Supabase Postgres URI — **not** the project URL (`https://...supabase.co`) |
| `JWT_SECRET_KEY` | _(auto-generated)_ | Render generates this — do not change after first deploy |
| `ALLOWED_ORIGINS` | `https://yourapp.onrender.com` | Add Vercel URL if using Option B |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | From console.anthropic.com |
| `TWILIO_ACCOUNT_SID` | `AC...` | From Twilio console |
| `TWILIO_AUTH_TOKEN` | `27...` | From Twilio console |
| `TWILIO_WHATSAPP_FROM` | `whatsapp:+14155238886` | Your Twilio sandbox number |
| `TWILIO_VERIFY_SIGNATURE` | `false` | Set to `true` once webhook URL is configured |

### 2c. First deploy

After setting env vars, trigger a manual deploy. Watch the build logs for:
```
Application startup complete.
```

The health endpoint will be live at: `https://yourapp.onrender.com/health`

### 2d. Configure Twilio webhook

In Twilio console → **Messaging → Try it out → Send a WhatsApp message**:
- Set the **When a message comes in** webhook URL to:
  ```
  https://yourapp.onrender.com/webhook/twilio
  ```
- Method: `POST`

---

## Step 3 — Vercel (Optional: split frontend)

> Skip this if using Option A (Render full-stack). Come back to it when you migrate the frontend to React/Next.js.

1. Go to [vercel.com](https://vercel.com) → **New Project** → import your GitHub repo
2. **Framework Preset**: Other
3. **Output Directory**: `app/static`
4. No build command needed (static files only)
5. After deploy, note your Vercel URL (e.g. `https://bayitpro.vercel.app`)

### Update vercel.json

Replace every `RENDER_BACKEND_URL` in `vercel.json` with your actual Render URL:
```bash
# Example:
sed -i 's|RENDER_BACKEND_URL|bayitpro-backend.onrender.com|g' vercel.json
```
Then redeploy.

### Update Render CORS

In Render dashboard, update `ALLOWED_ORIGINS`:
```
https://bayitpro.vercel.app,https://bayitpro-backend.onrender.com
```

### WebSocket limitation

Vercel does not proxy WebSocket connections. When using the Vercel frontend, live ticket notifications (real-time updates) will not work. The rest of the app works normally via HTTP rewrites. This is acceptable for a demo.

---

## Environment Variables Reference

### Required for production

| Variable | Where to set | Description |
|----------|-------------|-------------|
| `DATABASE_URL` | Render | PostgreSQL connection string from Supabase |
| `JWT_SECRET_KEY` | Render | Random 32-byte hex string — never reuse across environments |
| `ENV` | Render | Must be `production` |
| `ALLOWED_ORIGINS` | Render | Comma-separated list of frontend URLs |

### Required for WhatsApp

| Variable | Where to set | Description |
|----------|-------------|-------------|
| `TWILIO_ACCOUNT_SID` | Render | From Twilio console |
| `TWILIO_AUTH_TOKEN` | Render | From Twilio console — treat as a password |
| `TWILIO_WHATSAPP_FROM` | Render | `whatsapp:+1...` format |
| `TWILIO_VERIFY_SIGNATURE` | Render | Set to `true` in production |

### Required for LLM triage

| Variable | Where to set | Description |
|----------|-------------|-------------|
| `ANTHROPIC_API_KEY` | Render | From console.anthropic.com |

### Optional tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_MODEL` | `claude-haiku-4-5-20251001` | Model for ticket triage |
| `LLM_TIMEOUT_SECONDS` | `15` | Abort LLM call after N seconds |
| `JWT_EXPIRE_MINUTES` | `480` | Token lifetime (8 hours) |
| `DB_POOL_SIZE` | `10` | PostgreSQL connection pool size |
| `DB_MAX_OVERFLOW` | `20` | Max connections above pool size |

---

## Database Migrations

Migrations use Alembic. The `DATABASE_URL` environment variable is used automatically (see `alembic/env.py`).

```bash
# Run all pending migrations
alembic upgrade head

# Check current migration state
alembic current

# Roll back one migration
alembic downgrade -1
```

> **Fresh Supabase database**: Run `alembic upgrade head` once from your local machine with `DATABASE_URL` pointing to Supabase before your first Render deploy.

> **Existing SQLite database**: Migration `001_multi_tenant_foundation` may already be stamped. Check with `alembic current`.

---

## Local Development

```bash
# 1. Create venv and install deps
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Copy env file
cp .env.example .env
# Edit .env — at minimum, no changes needed for SQLite local dev

# 3. Run migrations (creates SQLite DB)
alembic upgrade head

# 4. Seed demo data (development only)
curl -X POST http://localhost:8000/seed

# 5. Start server
uvicorn app.main:app --reload

# App is at http://localhost:8000
# Default login: admin / admin123
```

---

## Production Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Render free tier sleeps after 15 min inactivity | Medium | Upgrade to Starter ($7/mo) or use UptimeRobot to ping `/health` |
| Supabase free tier pauses after 1 week of inactivity | Medium | Keep the app active or upgrade to Supabase Pro |
| Default admin `admin123` password | High | Change via `PATCH /auth/me` immediately after first login |
| `.env` committed to git | Critical | `.gitignore` now blocks this — **rotate any credentials that were in git history** |
| WebSocket not available on Vercel | Low | Use Render full-stack (Option A) for demo |
| `alembic stamp head` required for existing DBs | Medium | Document in runbook — do not run `upgrade head` blindly on prod |

---

## Rollback

```bash
# Roll back last migration
alembic downgrade -1

# Roll back to specific revision
alembic downgrade 001_multi_tenant_foundation

# Full rollback (destroys data)
alembic downgrade base
```

On Render: use **Manual Deploy → Deploy a specific commit** to roll back the application code.

---

## Troubleshooting

**`502 Bad Gateway` on Render**
→ Check build logs. Usually means `uvicorn` failed to start. Common cause: missing env var causing `RuntimeError` in `config.py`.

**`CORS error` in browser**
→ `ALLOWED_ORIGINS` on Render does not include your frontend domain. Update and redeploy.

**`alembic.util.exc.CommandError: Target database is not up to date`**
→ Run `alembic upgrade head`.

**`RuntimeError: JWT_SECRET_KEY must be set`**
→ `ENV=production` but `JWT_SECRET_KEY` is still the default. Set a real value in Render dashboard.

**`sqlalchemy.exc.OperationalError: no such column`**
→ Migrations not run on this database. Run `alembic upgrade head`.

**WebSocket connects then immediately disconnects**
→ Render free tier may be sleeping. Ping `/health` first to wake it.
