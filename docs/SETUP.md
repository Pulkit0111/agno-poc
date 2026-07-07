# Bott — Setup & Go-Live Guide

Follow this top to bottom. By the end, Bott runs and you can talk to it in Slack. Each item
says **where to go, what to click, what to copy**, and **where to put it in the codebase**.

Two kinds of item:
- 🧑‍💻 **You** — you can do it yourself.
- 🏢 **Axelerant admin** — an org-level thing that needs a Workspace/Google/GitHub/Atlassian admin. These are shared org credentials, set up once.

> **TL;DR minimal path** (just to chat with Bott in Slack): do **§1 Install**, **§2 `.env`**, **§4 Secret key**, **§5 Model (Codex)**, **§6 Slack**. §3 (a database) is **optional** — SQLite is the zero-setup default. Connectors (§7–§11) are optional — Bott just says "not configured" until you add them. §12 is the admin summary. §13 is the run + first test.

---

## Where things live in the codebase

- **All configuration** goes in a single file: **`.env`** in the repo root (`/Users/pulkittyagi/Desktop/agno/.env`). It's git-ignored. Copy the template: `cp .env.example .env` and edit it. Every setting below is a line in this file.
- **Secret files** (Google service-account JSON, GitHub App private key `.pem`) go in a git-ignored folder: **`.secrets/`** in the repo root. Create it once: `mkdir -p .secrets`. (`.secrets/` and `*.pem` are already in `.gitignore`.) In `.env` you point at them by path.
- Nothing else needs editing — the app reads everything from `.env`.

---

## §1 — Install (🧑‍💻 You)

Prereqs: Python ≥ 3.10 and [uv](https://docs.astral.sh/uv/) (or plain pip), and Postgres (§3).

```bash
cd /Users/pulkittyagi/Desktop/agno
uv sync                      # installs deps into .venv  (or: python -m venv .venv && .venv/bin/pip install -e .)
cp .env.example .env         # your config file
mkdir -p .secrets            # for key files
```

---

## §2 — The `.env` file (🧑‍💻 You)

Everything below is a `KEY=value` line in `.env`. Lines starting with `#` are comments. No quotes needed. After editing, no restart trick is needed — you start the server once at the end (§13).

---

## §3 — Database (🧑‍💻 You) — **optional for local testing**

Bott stores everything in one database (memory, jobs, approvals, secrets, skills). The code
picks the DB automatically:

- **Default (zero setup):** if `DATABASE_URL` is **unset**, Bott uses a local **SQLite** file
  (`agentos.db` in the repo). Fine for local Slack testing — **you don't need to install
  anything.** Skip to §4.
- **Production (recommended for real use):** set `DATABASE_URL` to a Postgres instance:
  ```
  DATABASE_URL=postgresql://user:pass@host:5432/bott
  ```
  (Create the DB first, e.g. `createdb bott`.) Tables are created automatically on first run
  either way — nothing to migrate by hand.

---

## §4 — Encryption key (🧑‍💻 You)

Bott encrypts stored secrets at rest (Fernet). Generate one key and keep it stable:

```bash
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output into `.env`:
```
BOTT_SECRET_KEY=<paste the generated key>
```
> Keep this safe. If it changes, previously-encrypted values (e.g. the stored Codex token) can't be read.

---

## §5 — Model provider: Codex (ChatGPT subscription) (🏢 Axelerant admin — org-level)

Bott's brain runs on the **org's ChatGPT/Codex subscription** — one shared login, no per-user API keys. This is org-level.

In `.env`:
```
MODEL_PROVIDER=codex
```

Then connect the org Codex token **one of two ways**:

- **Easiest (host has the Codex CLI):** on the machine that runs Bott, an admin logs in once with the ChatGPT/Codex CLI so a token file exists at `~/.codex/auth.json`. Bott auto-imports it at startup. Nothing else to set.
  - Run `codex login` (the ChatGPT/Codex CLI) using the org's ChatGPT account, complete the browser login, confirm `~/.codex/auth.json` exists.
- **Or from Slack (after the app is up):** an admin opens Bott's **App Home** tab in Slack → **Models** section → **Connect Codex**, and pastes the contents of a `~/.codex/auth.json`. (Admin-gated — your email must be in `BOTT_ADMINS`, §11.)

> Later, to use Bedrock or OpenRouter instead, set `MODEL_PROVIDER=bedrock`/`openrouter` and their keys (`OPENROUTER_API_KEY`, AWS creds). Not needed for first test.

---

## §6 — Slack app (🏢 Axelerant admin to create the app in the workspace; 🧑‍💻 you can fill `.env`)

This is what lets you talk to Bott. Bott receives Slack events over **HTTPS request URLs**, so the server must be reachable at a public URL.

### 6a. Make the server reachable
- **Local testing:** run a tunnel to the local port (default `7777`), e.g.:
  ```bash
  # example with cloudflared or ngrok — pick one you have
  ngrok http 7777
  ```
  Note the public HTTPS base URL it gives you, e.g. `https://abc123.ngrok.app`. Call it **`BASE`** below.
- **Deployed:** `BASE` is your server's public HTTPS URL.

### 6b. Create the Slack app
1. Go to **https://api.slack.com/apps** → **Create New App** → **From scratch**. Name it "Bott", pick the Axelerant workspace. (Creating apps may require a workspace admin to approve — 🏢.)
2. **OAuth & Permissions** → **Scopes** → **Bot Token Scopes**, add:
   `app_mentions:read`, `chat:write`, `im:history`, `im:read`, `im:write`, `channels:history`, `channels:read`, `groups:history`, `groups:read`, `users:read`, `users:read.email`. (These let Bott read mentions/DMs, post, resolve your email for per-user isolation, and resolve channel names — `channels:read`/`groups:read` cover public/private channels respectively. Without `groups:read` the logs fill with benign `Failed to resolve channel name` warnings for private channels.)
   > **Already installed?** Adding a scope requires **reinstalling** the app (step 6, "Install to Workspace") for the new scope to take effect.
3. **App Home** → enable the **Home Tab** and **Messages Tab**; turn on **"Allow users to send Slash commands and messages from the messages tab"**.
4. **Event Subscriptions** → **Enable Events** → **Request URL:** `BASE/slack/events` (wait for the green "Verified"). Under **Subscribe to bot events** add: `app_mention`, `message.im`, `app_home_opened`.
5. **Interactivity & Shortcuts** → **On** → **Request URL:** `BASE/slack/interactivity`.
6. **Install App** → **Install to Workspace** → authorize.

### 6c. Copy the two values into `.env`
- **OAuth & Permissions** → **Bot User OAuth Token** (starts `xoxb-`):
  ```
  SLACK_BOT_TOKEN=xoxb-...
  ```
- **Basic Information** → **App Credentials** → **Signing Secret** → **Show**:
  ```
  SLACK_SIGNING_SECRET=<the signing secret>
  ```

> That's all Slack needs for this HTTP setup. (You may see `SLACK_APP_TOKEN` in `.env.example`; it's not required for this request-URL path — leave it blank.)

---

## §7 — Google Workspace: Gmail + Drive + Calendar (🏢 Axelerant admin — org-level, read-only)

One org **service account** with **domain-wide delegation** lets Bott read *each user's own* Gmail/Drive/Calendar (read-only). Isolation is enforced by Bott (it only ever impersonates the verified Slack caller). A **Google Workspace super-admin** does this once.

### 7a. Create the service account + key (Google Cloud Console)
1. Go to **https://console.cloud.google.com** → pick/create a project.
2. **APIs & Services** → **Enabled APIs & services** → **+ Enable APIs** → enable **Gmail API**, **Google Drive API**, **Google Calendar API**.
3. **APIs & Services** → **Credentials** → **Create credentials** → **Service account**. Name it e.g. `bott-readonly`. Create.
4. Open the service account → **Keys** → **Add key** → **Create new key** → **JSON** → download. **Note its "Unique ID" / client ID** (a long number) — you need it in 7b.

### 7b. Authorize domain-wide delegation (Google Admin Console)
1. Go to **https://admin.google.com** (must be a Workspace super-admin).
2. **Security** → **Access and data control** → **API controls** → **Domain-wide delegation** → **Add new**.
3. **Client ID** = the service account's Unique ID from 7a.
4. **OAuth scopes** (comma-separated) — paste exactly these three (read-only):
   ```
   https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/calendar.readonly
   ```
5. **Authorize**.

### 7c. Put the key file + point `.env` at it (🧑‍💻 You)
- Save the downloaded JSON to `.secrets/google-sa.json` in the repo.
- In `.env`:
  ```
  GOOGLE_SERVICE_ACCOUNT_PATH=.secrets/google-sa.json
  ```
> Until this is set, `gmail_search`/`drive_search`/`calendar_list_events` just won't appear — no error.

---

## §8 — Sentry (🏢 Axelerant admin — org-level, read-only)

Lets Bott read incidents and run triage.

1. Go to **https://sentry.io** → **Settings** (org) → **Developer Settings** → **Internal Integrations** → **Create New Internal Integration** (or **Auth Tokens** for a personal token).
2. Give it **Read** permissions for **Issue & Event** and **Project** (`event:read`, `project:read`).
3. Copy the generated **token**. Note your **organization slug** (in the URL: `sentry.io/organizations/<slug>/`).
4. In `.env`:
   ```
   SENTRY_ORG_SLUG=<your-org-slug>
   SENTRY_API_TOKEN=<the token>
   # SENTRY_BASE_URL=https://sentry.io   # only if self-hosted
   ```

---

## §9 — GitHub App: build, fix & triage PRs (🏢 Axelerant admin — org-level)

Bott opens **draft PRs** when it implements a fix (from a request, a Jira ticket, or a Sentry triage). It uses a **GitHub App** installed on the repos it may touch.

### 9a. Create + install the GitHub App (org admin)
1. Go to **https://github.com/organizations/<org>/settings/apps** → **New GitHub App**.
2. **Repository permissions:** **Contents** = Read & write, **Pull requests** = Read & write, **Metadata** = Read-only. (For webhook auto-review add **Issues**/**Webhooks** as needed.)
3. **Webhook:** set a **Webhook secret** (any strong random string — save it). Webhook URL (optional, for auto-review) = `BASE/webhook/github`.
4. **Create**, then **Generate a private key** → downloads a `.pem`.
5. **Install App** → choose the specific repos Bott may open PRs on.
6. Note the **App ID** (on the app's General page).

### 9b. Put the key + point `.env` at it (🧑‍💻 You)
- Save the `.pem` to `.secrets/github-app.pem`.
- In `.env`:
  ```
  GITHUB_APP_ID=<the app id>
  GITHUB_APP_PRIVATE_KEY_PATH=.secrets/github-app.pem
  GITHUB_WEBHOOK_SECRET=<the webhook secret from 9a>
  ALLOWED_POST_REPOS=axelerant/repo-one,axelerant/repo-two
  ```
  `ALLOWED_POST_REPOS` is the **allowlist** — Bott refuses to open a PR on any repo not listed here (build **and** triage). Comma-separated `owner/repo`.

---

## §10 — Jira / Confluence / Memra / Spin (🏢 Axelerant admin — org-level; likely already set)

These power sprint reports, portfolio, engagement lookups, and publishing. If Bott was already running these before, the values exist — just carry them into `.env`.

```
# Jira + Confluence (Atlassian API token: https://id.atlassian.com/manage-profile/security/api-tokens)
JIRA_BASE_URL=https://axelerant.atlassian.net
JIRA_EMAIL=<a service/admin atlassian account email>
JIRA_API_TOKEN=<atlassian api token>
# Confluence falls back to the Jira creds unless overridden (CONFLUENCE_URL/USERNAME/API_KEY).

# Memra (org context layer) — from the Memra team:
MEMRA_CLIENT_ID=
MEMRA_CLIENT_SECRET=
MEMRA_TOKEN_ENDPOINT=
MEMRA_MCP_ENDPOINT=
MEMRA_SCOPE=

# Spin (publishing rendered reports to a hosted URL) — if used:
SPIN_API_BASE_URL=
SPIN_API_TOKEN=
SPIN_PUBLIC_ZONE=
```
Each is independent — leave any blank and that feature just stays off.

---

## §11 — Admins & org domain (🧑‍💻 You)

```
BOTT_ADMINS=pulkit.tyagi@axelerant.com          # comma-separated; gates the skill curator + model overrides
ALLOWED_EMAIL_DOMAIN=axelerant.com              # default; only these users are recognized
```
Put your own email in `BOTT_ADMINS` so you can connect Codex from App Home and pin/retire skills.

---

## §12 — What must come from the Axelerant admin (org-level) — summary

| # | Thing | Who | What they hand you |
|---|---|---|---|
| §5 | ChatGPT/Codex org login | Workspace/ChatGPT admin | `~/.codex/auth.json` on the host, or paste via App Home |
| §6 | Slack app in the workspace | Slack workspace admin | `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` (+ app installed) |
| §7 | Google service account + domain-wide delegation (gmail/drive/calendar `.readonly`) | Google Workspace super-admin | the `google-sa.json` key file |
| §8 | Sentry read token | Sentry org admin | `SENTRY_ORG_SLUG`, `SENTRY_API_TOKEN` |
| §9 | GitHub App installed on the repos | GitHub org admin | `GITHUB_APP_ID`, the `.pem`, `GITHUB_WEBHOOK_SECRET`, repo list |
| §10 | Jira/Confluence/Memra/Spin creds | Atlassian admin + Memra team | tokens/endpoints above |

Everything else (§1–§4, §11, §13) you can do yourself.

---

## §13 — Run it & first Slack test (🧑‍💻 You)

1. Make sure `.env` has at least: `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, and `BOTT_SECRET_KEY` (+ the Codex token via §5; `MODEL_PROVIDER` defaults to `codex`). No `DATABASE_URL` needed — it uses SQLite by default (§3).
2. Start the tunnel (§6a) if testing locally, and confirm the Slack **Event Subscriptions** Request URL shows **Verified**.
3. Start Bott:
   ```bash
   uv run bott-app          # or: .venv/bin/bott-app
   ```
   You should see logs: schema created, worker started, and either "Seeded org Codex token…" or the app waiting. If you see "Slack interface NOT mounted", `SLACK_BOT_TOKEN`/`SLACK_SIGNING_SECRET` are missing.
4. In Slack: open a **DM with Bott** (or `@Bott` in a channel it's in) and say **"hi, what can you do?"**. It should reply. Try **"search my email for the latest invoice"** (needs §7) or **"list my skills"**.
5. Open Bott's **App Home** tab → confirm the Models section; an admin can **Connect Codex** here if not seeded on the host.

### If something's off
- **No reply in Slack:** the Request URL isn't reaching the server (tunnel down, wrong `BASE`, or signing secret mismatch). Re-verify the Event Subscriptions URL.
- **"…isn't configured" replies:** that connector's `.env` values are missing — see the relevant section. This is expected and safe.
- **Codex errors:** the org token isn't connected — do §5 (host `~/.codex/auth.json` or App Home → Connect Codex).

---

## §14 — After you're chatting: the live checks I'll run

Once §5–§9 are in place, tell me and I'll verify end-to-end (these need real credentials, so they're done after you provision):
- **Google:** a real "only *my* mail / drive / calendar" round-trip (proves per-user isolation).
- **Sentry:** a live issue read + a full `triage → approve → draft PR` on an allowlisted repo.
- **Codex:** `scripts/eval_codex.py` (spends one real Codex call — I'll run it only on your go-ahead).

---

### Absolute-minimum `.env` to chat in Slack
```
# No DATABASE_URL → uses local SQLite (agentos.db). Add it only for Postgres/production.
BOTT_SECRET_KEY=<from §4>
# MODEL_PROVIDER defaults to codex — no line needed; connect the token via §5.
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
BOTT_ADMINS=pulkit.tyagi@axelerant.com
```
(+ the Codex token via §5, and the tunnel + Slack request URLs via §6.) Add connectors (§7–§10) whenever you're ready — just add the lines and restart the server.

> **Note:** the repo's checked-in `.env.example` was refreshed to match the current app
> (`MODEL_PROVIDER`, SQLite default, `SLACK_SIGNING_SECRET`, the connector groups). The old
> template used `SLACK_APP_TOKEN`/`MODEL_BACKEND`/`run_server.sh`, which the current code no
> longer uses — if your `.env` still has those, follow the sections above instead.

---

## Web console

The management console (Next.js app in `console/`) talks to `/api/console/*`.

Env (in `.env`):
- `CONSOLE_SESSION_SECRET` — long random string; enables the console API.
- `SLACK_CLIENT_ID` / `SLACK_CLIENT_SECRET` — from the BottPOC Slack app
  (Basic Information). Add `<CONSOLE_BASE_URL>/api/console/auth/callback`
  to the app's **OpenID Connect** redirect URLs.
- `CONSOLE_BASE_URL` — where the console is served (dev: `http://localhost:3000`).

Dev: `uv run bott-app` (API on :8000) and `cd console && npm run dev` (:3000,
proxies `/api/*` to :8000).
