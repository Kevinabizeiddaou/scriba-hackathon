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

Deploy Scriba with the overlay (`APP_MODULE=desk_overlay.asgi:app`, `backend/` on
`PYTHONPATH`; see [backend/README.md](../backend/README.md)). Add a Postgres database.

Set these, with `DESK` being the Desk's public origin, for example
`https://scriba-desk.vercel.app`, or the custom domain if one is used:

| Variable | Value |
| --- | --- |
| `GOOGLE_CLIENT_ID` | Scriba's existing OAuth client |
| `GOOGLE_CLIENT_SECRET` | Scriba's existing OAuth client |
| `GOOGLE_REDIRECT_URI` | `DESK/api/oauth/callback` |
| `APP_FRONTEND_URL` | `DESK` |
| `ALLOWED_ORIGINS` | `DESK`. Without it Scriba's cross-site guard refuses every POST |
| `APP_BASE_URL` | `DESK/api` |
| `APP_SESSION_COOKIE_DOMAIN` | empty (the cookie belongs to the Desk's host) |
| `DATABASE_URL` | Railway Postgres |
| `SESSION_SECRET_KEY`, `ENCRYPTION_KEY` | New values for this deployment. Never Scriba production's |

The full list of Scriba's settings is `env.template` in the Scriba checkout.

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
