# Jira: what to configure, in order

A checklist for whoever holds the Atlassian developer console and the Railway project.
Nothing here is a secret; no value belongs in this file or in Git.

The Desk adds no second sign-in. It reuses Scriba's own Jira OAuth flow, token store and
refresh, which are already in the hosted API and currently report `missing_credentials`
(`GET /api/providers/status`, `providers.jira`).

## 1. Atlassian developer console

<https://developer.atlassian.com/console/myapps/>

1. **Create** → **OAuth 2.0 integration**. Name it (for example "Scriba Executive Desk").
2. **Permissions** → add **Jira API**, then **Configure** and add the scopes in section 3.
   Add **Jira Service Management API** only if approvals on service requests are wanted.
3. **Authorization** → OAuth 2.0 (3LO) → **Configure** → **Callback URL**:

   ```
   https://scriba-hackaton.vercel.app/api/auth/jira/callback
   ```

   It must go through the Desk's `/api` proxy, like the Google callback: Scriba binds a
   sign-in to the browser that started it with a cookie on the Desk's origin
   ([DEPLOY.md](../DEPLOY.md)). `GET /desk/jira/status` shows the exact URL the server will
   use (`setup.callbackUrl`).
4. **Settings** → copy the **Client ID** and the **Secret** (step 2 below).
5. **Distribution** → **Enable sharing**, if anyone other than the app's owner will connect.
   An app is private by default: only its owner's Atlassian account can authorize it.

## 2. Railway (API service) variables

| Variable | Value |
| --- | --- |
| `JIRA_CLIENT_ID` | From the console, Settings |
| `JIRA_CLIENT_SECRET` | From the console, Settings |
| `JIRA_SCOPES` | The scopes of section 3, separated by **spaces** |
| `JIRA_REDIRECT_URI` | Not needed: `APP_BASE_URL` is set, so Scriba derives the callback above. Set it only to override |
| `DESK_JIRA` | `on`. Without it the Desk has no Jira routes and no Jira screen |
| `DESK_JIRA_WRITES` | Leave unset at first. `on` lets an approved change reach the real site |
| `DESK_JIRA_WRITES_AUTHORIZED_BY` | The name of who switched writes on. Required with the line above |

Changing `JIRA_SCOPES`, or the scopes in the console, means every connected person
reconnects once: Atlassian asks for consent again.

## 3. Scopes

Scriba's default is `read:jira-work read:jira-user write:jira-work offline_access`.
Project reads (`GET /desk/jira/projects` and `/desk/jira/projects/{key}`, which also feed
the project picker when creating an issue) depend on `read:project:jira`: without it they
answer 403 `scope_missing` and the Coverage tab names the scope. It is read-only.
Boards and sprints need the granular Jira Software
scopes: Jira Software has no classic ones, so the two kinds are mixed (Atlassian asks for
fewer than 50 in total; this is 14).

| For | Scopes |
| --- | --- |
| Issues, filters, comments (read) | `read:jira-work` |
| Projects: the list, one project, its issue types and components (read) | `read:project:jira` |
| People to assign and mention | `read:jira-user` |
| Create and change issues, comment, log time | `write:jira-work` |
| Stay connected | `offline_access` |
| Boards, backlogs, sprints, epics (read) | `read:board-scope:jira-software` `read:sprint:jira-software` `read:epic:jira-software` `read:issue-details:jira` `read:jql:jira` (and `read:project:jira` above) |
| A board's columns | `read:board-scope.admin:jira-software` |
| Plan sprints | `write:sprint:jira-software` `write:board-scope:jira-software` `write:issue:jira-software` |
| Optional: create and release versions | `manage:jira-project` |
| Optional: service request approvals | `read:servicedesk-request` `write:servicedesk-request` |

The value for `JIRA_SCOPES` without the optional rows:

```
read:jira-work read:project:jira read:jira-user write:jira-work offline_access read:board-scope:jira-software read:sprint:jira-software read:epic:jira-software read:issue-details:jira read:jql:jira read:board-scope.admin:jira-software write:sprint:jira-software write:board-scope:jira-software write:issue:jira-software
```

A connection made with fewer scopes still works: the Coverage tab and
`GET /desk/jira/features` say which features it cannot reach and which scopes to add.

## 4. Check it

1. `GET /api/providers/status` → `providers.jira.status` is `disconnected`, no longer `unavailable`.
2. Sign in to the Desk. **Jira** appears in the navigation (only with `DESK_JIRA=on`).
3. **Connect Jira**, choose the site at Atlassian, come back to the Desk signed in.
4. The Briefing tab loads. The Coverage tab shows no "Scope missing".
5. Prepare a comment on a test issue and approve it. With `DESK_JIRA_WRITES` unset it must say
   **Held** and the issue must be unchanged. Only then decide whether to switch writes on.

## 5. Know before connecting on the hosted API

These are Scriba's own behaviours, which the Desk does not change:

- **Connecting runs Scriba's sync inside the callback**: up to 100 recent issues are stored, and
  each is sent through one model call. The model is on in the hosted API, so the first
  connect costs model usage and takes a while to return.
- **Scriba's own `/jira/*` routes are mounted too** and write to Jira directly, with no
  approval step. The Desk's screens never call them, and `DESK_JIRA_WRITES` does not govern
  them: it governs only changes approved through the Desk.
- **Once `JIRA_CLIENT_ID` is set, `/auth/jira/login` also works as a sign-in** and can create a
  Scriba account from an Atlassian identity.
- **One site per person.** Scriba keeps the first site of a grant.
- **OAuth apps share a rate quota** (65,000 points an hour across all sites since March 2026;
  a request costs 1 point plus 1 per issue returned). The Desk asks only for the fields it
  shows, waits once on a short `Retry-After`, and otherwise reports the limit.

## Local demo, no credentials

```
DESK_DEMO=on DESK_JIRA=on docker compose up -d
```

Sign in as a seeded user and open **Jira**: it runs on a synthetic site, labelled Simulated.
