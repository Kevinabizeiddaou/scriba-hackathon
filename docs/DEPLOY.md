# Hosted deployment: Desk on Vercel, API on Railway

The Desk is a static build on Vercel. The API (Scriba with the Desk overlay) runs on
Railway. Google sign-in reuses **Scriba's existing Google Cloud project and OAuth
client**: no new client is created.

## Why the API goes through `/api` on the Desk's own origin

Scriba keeps the session in a cookie and the Desk sends it on every request
(`credentials: 'include'`). If the browser called Railway directly, that cookie would
belong to another site (`*.vercel.app` and `*.up.railway.app` are different sites).
Safari blocks such cookies and Firefox and Brave usually drop them, so people would
sign in and then appear signed out.

So the Desk is built with `VITE_API_BASE_URL=/api` and Vercel proxies `/api/*` to
Railway ([`vercel.json`](../vercel.json)). For the browser, the API is on the Desk's
own origin and the cookie is first-party everywhere.

The Google callback must go through the proxy too. Scriba binds each Google sign-in
to the browser that started it with a cookie set by `/auth/login`. That cookie is on
the Desk's origin, so the callback has to arrive there as well.

## 1. Railway (API)

The API image is [`backend/Dockerfile.railway`](../backend/Dockerfile.railway), and
[`railway.json`](../railway.json) tells Railway to build it. The image is Scriba's real
application at a pinned commit with the overlay mounted (`desk_overlay.asgi:app`).
Scriba's code is not in this repository, so the build fetches it from GitHub with a
read-only token. The token is used only in a build stage that is thrown away and never
reaches the final image.

1. **Token.** Create a fine-grained GitHub personal access token with resource owner
   `ScribaAssist`, repository access limited to `ScribaAssist/Scriba`, and the
   **Contents: Read-only** permission. The organisation may have to approve it.
2. **Project.** In Railway, create a project from this GitHub repository (root directory:
   the repository root), then add a **PostgreSQL** database to the project.
3. **Variables** on the API service. `DESK` is the Desk's public origin, for example
   `https://scriba-desk.vercel.app`, or the custom domain if one is used:

| Variable | Value |
| --- | --- |
| `SCRIBA_GITHUB_TOKEN` | The token from step 1. Railway passes it to the build |
| `SCRIBA_REF` | Optional. The Scriba commit to build; defaults to the one the overlay is tested with |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (a reference to the Railway database) |
| `APP_ENV` | `production` |
| `SESSION_SECRET_KEY` | New value: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ENCRYPTION_KEY` | New value: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Back it up: losing it makes stored Google tokens unreadable |
| `GOOGLE_CLIENT_ID` | Scriba's existing OAuth client |
| `GOOGLE_CLIENT_SECRET` | Scriba's existing OAuth client |
| `GOOGLE_REDIRECT_URI` | `DESK/api/oauth/callback` |
| `APP_FRONTEND_URL` | `DESK` |
| `APP_BASE_URL` | `DESK/api` |
| `ALLOWED_ORIGINS` | `DESK`. Without it Scriba's cross-site guard refuses every POST |
| `APP_SESSION_COOKIE_DOMAIN` | Empty (the cookie belongs to the Desk's host) |
| `DESK_CHAT_SCOPE` | `on`. This process serves only the Desk (see [backend/README.md](../backend/README.md)) |
| `TRUSTED_PROXY_HOPS` | `2` (Vercel's proxy, then Railway's edge). To confirm after the first deploy |

   Never reuse Scriba production's `SESSION_SECRET_KEY` or `ENCRYPTION_KEY`. The full list
   of Scriba's settings is `env.template` in the Scriba checkout.
4. **Domain.** Under the service's Settings, Networking, generate a public domain. That
   host replaces `RAILWAY_API_HOST` in `vercel.json`. The image listens on Railway's
   `PORT`, and Railway checks `/health` before switching traffic to a new deploy.

**Background jobs.** Scriba starts its own schedulers in this process: daily briefs,
Gmail sync, automation triggers and others. `RUN_SCHEDULERS=false` turns them all off
while the API keeps serving. The Desk's execution gate holds mail and calendar actions
approved through it (`external_writes_enabled=False` in the startup log), but it does not
govern what Scriba's own schedulers do.

**Checked locally** (the image built from an export of Scriba at the pinned commit, with a
throwaway Postgres and `APP_ENV=production`): Scriba creates its tables and starts, `/health`
and `/ready` answer, `/ready` reports the production profile ready, the 69 `/desk` routes are
mounted with the execution gate and the chat scope on, and `/auth/login` redirects to Google
with `DESK/api/oauth/callback` as the redirect URI. Not checked: the GitHub fetch with a real
token, and anything on Railway itself.

To build the same image locally without a token, export Scriba and pass the export as the
`scriba-source` build context, which replaces the fetch stage:

```bash
git -C <scriba checkout> archive 3ae3a2aa0c2dd2398f5a2e6b0d3ce1eaeeb0fdf7 | tar -x -C <export dir>
docker build -f backend/Dockerfile.railway --build-context scriba-source=<export dir> -t desk-api .
```

## 2. Vercel (Desk)

1. Import this repository in Vercel. Leave the root directory as the repository root:
   `vercel.json` sets the install command, build command and output.
2. In `vercel.json`, replace `RAILWAY_API_HOST` with the Railway service's public host
   (for example `scriba-desk-api.up.railway.app`), commit, and deploy.

The build runs `npm run build` (typecheck, then Vite). The Docker-only guard covers
only the dev and preview servers, so it does not affect Vercel.

## 3. Scriba's Google OAuth client

In Scriba's Google Cloud project, on the existing **Web application** OAuth client,
add this authorized redirect URI:

```
DESK/api/oauth/callback
```

Nothing else changes: same APIs (Gmail, Calendar, People, Drive), same scopes, same
consent screen.

**Domain:** if Scriba's consent screen is published (in production), every redirect
URI must be on one of its authorized domains. A `*.vercel.app` host is not one, and
adding a new authorized domain to a verified app can send the consent screen back
for verification. Serving the Desk from a subdomain of Scriba's own domain avoids
this: add it as a custom domain in Vercel (a CNAME record) and use it as `DESK`.

## Checking it

After the first deploy, open `DESK/api/providers/status`. It should answer from
Scriba (JSON), not with the Desk's page. Then sign in with Google and check that:

- the browser comes back to the Desk signed in,
- the `scriba_session` cookie is on the Desk's host, not on Railway's,
- a reload keeps you signed in, in Safari or Firefox as well as Chrome.
