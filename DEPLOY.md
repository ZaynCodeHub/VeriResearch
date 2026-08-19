# Deploying VeriResearch

This deploys two services (backend API, frontend static site) plus a managed
Postgres database, on Railway.

## Current deployment

- Frontend: https://veriresearch-frontend-production.up.railway.app
- Backend: https://veriresearch-backend-production.up.railway.app (`/health`)
- Project: "veriresearch" in Zayn's Railway workspace, three services
  (`veriresearch-backend`, `veriresearch-frontend`, `Postgres`) in the
  `production` environment.
- Both app services are connected to `ZaynCodeHub/VeriResearch` on `main` —
  pushing to `main` triggers a new build and deploy automatically for
  whichever service's files changed.

### Operating notes

- **`railway redeploy` replays the previous deployment's build config
  verbatim** — it does not re-read current service settings (root directory,
  Dockerfile path, etc.). If you change a build-affecting setting, it only
  takes effect on the *next* build triggered by an actual GitHub push (or
  `railway up`), not on a `redeploy` of the old one. Learned this the hard
  way getting the frontend's root directory pointed at `frontend/` — the fix
  didn't show up until an actual push.
- `VITE_API_BASE` is baked into the frontend at **build** time. If the
  backend's URL ever changes, update that variable and push (or `railway up`)
  to rebuild — restarting the running frontend container won't pick it up.
- Useful commands from the repo root (Railway CLI, already linked to this
  project): `railway status --json`, `railway logs --service <name>`,
  `railway variable list --service <name> --kv`, `railway domain --service <name>`.

## Setting this up from scratch (reference)

The above is already done. This section is for redoing it — a new
environment, a fork, or if the project ever needs to be recreated. Everything
below is manual dashboard/CLI work either way — I can't create an account or
bind a payment method for you.

The app ships defaulting to **offline/demo mode**: no `GROK_API_KEY` or
`TAVILY_API_KEY` needed, deterministic output from the bundled local corpus
and heuristic judge, zero external API cost. You can flip on live mode later
by setting those two variables — no code or redeploy-config changes needed.

## 0. Verify locally first (optional but recommended)

If you have Docker Desktop running:

```
docker compose up --build
```

Then open http://localhost:8080 (frontend) — it should be able to create a
run against the backend at http://localhost:8000. This exercises the exact
Dockerfiles Railway will build, against a real Postgres, before you spend any
cloud credits debugging a build issue.

## 1. Create a Railway account

1. Go to https://railway.app and sign up (GitHub login is simplest — it also
   makes step 3 one click).
2. Add a payment method under **Account Settings → Billing** if you're past
   the free trial credit. A single small backend + frontend + Postgres setup
   is inexpensive, but Railway does require a card on file beyond the trial.

## 2. Create the project and Postgres

1. **New Project → Deploy PostgreSQL**. Railway provisions a Postgres
   instance and exposes its connection string as `DATABASE_URL` on that
   plugin's own **Variables** tab — you'll reference it, not retype it.

## 3. Deploy the backend

1. In the same project: **New → GitHub Repo** → select `ZaynCodeHub/VeriResearch`.
2. Railway will try to autodetect a build method. Since there's a
   `Dockerfile` at the repo root, tell it to use that (Settings → Build →
   Builder → Dockerfile) if it doesn't pick it automatically.
3. **Settings → Networking → Generate Domain** — gives you a public URL like
   `https://veriresearch-backend-production.up.railway.app`. Note it, you'll
   need it in step 4.
4. **Variables** tab, add:
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` (Railway's variable
     reference syntax — type this literally, it resolves the Postgres
     plugin's connection string; use the actual service name shown in your
     project if it's not "Postgres").
   - `CORS_ORIGINS` = leave blank for now, you'll fill this in after step 4
     once the frontend has a URL.
   - `MAX_CONCURRENT_RUNS` = `5` (or leave unset, that's the default).
5. Deploy. Check `https://<backend-url>/health` returns `{"status":"ok"}`.

## 4. Deploy the frontend

1. **New → GitHub Repo** → same repo again, but set **Root Directory** to
   `frontend` (Settings → Source → Root Directory) so Railway builds
   `frontend/Dockerfile` instead of the backend one.
2. **Variables** tab, add `VITE_API_BASE` = the backend URL from step 3.3
   (e.g. `https://veriresearch-backend-production.up.railway.app`). This is
   read at **build** time, not runtime — Vite inlines it into the JS bundle.
3. **Settings → Networking → Generate Domain** for the frontend too.
4. Deploy.

## 5. Close the loop: lock CORS to the real frontend URL

1. Back on the **backend** service's Variables tab, set `CORS_ORIGINS` to the
   frontend URL from step 4.3 (e.g.
   `https://veriresearch-frontend-production.up.railway.app`). Railway
   redeploys automatically on variable change.
2. Open the frontend URL, start a run, confirm it completes and claim
   evidence lookups work.

## 6. (Optional) Turn on live mode

On the backend service's Variables tab, add `GROK_API_KEY` (xAI) and/or
`TAVILY_API_KEY` (Tavily search). Redeploy is automatic. Without these the
app runs fully offline as described above — there's no reason to add them
until you specifically want live web search and LLM-drafted reports.

## What's still not here

This setup gets you a real persistent, restart-safe, resource-bounded
deployment — not a fully hardened production system. Explicitly out of scope
unless you ask for it next:

- **Auth** — the API is open to anyone with the URL. Fine for a demo/portfolio
  deploy; not fine if this ever handles anything sensitive or costs real
  money per request (live mode does, via the LLM/search APIs).
- **Structured logging/metrics/alerting** — you get Railway's basic
  logs/metrics dashboard, nothing beyond that.
- **Autoscaling / multi-region** — single instance per service.
- Note on CD: GitHub push-to-deploy *is* wired up (see "Current deployment"
  above). `.github/workflows/ci.yml` only *tests* — it's a separate thing,
  not what triggers the Railway deploys.
