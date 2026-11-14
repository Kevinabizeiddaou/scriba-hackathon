"""Jira for the Desk. A skeleton: see docs/jira/README.md.

Off unless ``DESK_JIRA`` is set. It adds routes under ``/desk/jira/`` to the
Desk overlay and nothing to Scriba: sign-in, the stored connection and the
token refresh are Scriba's own (``/auth/jira/login``, its connected-accounts
table, ``app.jira_client.get_access_token``), reached through the gateway.

Reads go straight to Jira Cloud's REST API. A write is never made directly:
it is recorded as a proposal with a preview, a person approves it, and only
then does it run, behind a switch that is off by default (``policy.py``).

| Module | What it is |
| --- | --- |
| ``policy.py`` | The switches, and which scopes each feature needs (pure) |
| ``adf.py`` | Atlassian Document Format to and from plain text (pure) |
| ``jql.py`` | JQL from structured filters, and the named views (pure) |
| ``models.py`` | Jira's JSON as the shapes the Desk serves (pure) |
| ``insights.py`` | What an executive needs from a set of issues (pure) |
| ``features.py`` | Every Jira feature and how far the Desk covers it (pure) |
| ``client.py`` | Every REST call, over an injected transport |
| ``transport.py`` | The HTTP transport: token, site, rate limits |
| ``actions.py`` | The writes: validation, preview, execution, read-back |
| ``proposals.py`` | A proposed write, from preview to approval to outcome |
| ``sandbox.py`` | A synthetic Jira site for the demo and the tests |
| ``service.py`` | The operations behind the routes |
| ``routes.py`` | ``/desk/jira/*`` |
"""

__all__ = ["JIRA_SKELETON_VERSION"]

JIRA_SKELETON_VERSION = "0.1.0"
