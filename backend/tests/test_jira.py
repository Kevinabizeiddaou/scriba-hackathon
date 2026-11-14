"""Jira for the Desk: the pure modules, the client, the proposals and the routes.

No Scriba checkout and no network: the client talks to a scripted transport
or to the synthetic site, and the routes run on a fake gateway.
"""
import datetime as dt
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from desk_overlay.jira import actions, adf, features, insights, jql, models, policy, proposals
from desk_overlay.jira.client import JiraClient, JiraError
from desk_overlay.jira.routes import build_jira_router, health
from desk_overlay.jira.sandbox import JiraSite
from desk_overlay.jira.transport import (API_ROOTS, GATEWAY, GatewayTransport, JiraResponse,
                                         gateway_refused, scope_refused, url_for)
from desk_overlay.sandbox import RoutedGateway, SandboxWorld, WorldRegistry

from .fakes import FakeGateway

NOW = dt.datetime(2026, 11, 16, 9, 0, tzinfo=dt.timezone.utc)
EXEC = "exec@example.test"
OTHER = "other@example.test"
ON = {"DESK_JIRA": "on"}
WRITES_ON = {**ON, "DESK_JIRA_WRITES": "on", "DESK_JIRA_WRITES_AUTHORIZED_BY": "the project lead"}


class User:
    id = 1
    email = EXEC


def site():
    return JiraSite(owner_email=EXEC, now=lambda: NOW)


def context(jira_site):
    client = JiraClient(jira_site, sleep=lambda seconds: None)
    return actions.Context(client=client, field_map=models.FieldMap.from_fields(client.fields()),
                           me="sbx-me", site_url=jira_site.site_url)


# ── ADF ────────────────────────────────────────────────────────────────────

def test_adf_never_builds_an_empty_text_node():
    def texts(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                yield node["text"]
            for child in node.get("content") or []:
                yield from texts(child)

    for source in ("", "   ", "\n\n", "- \n", "# ", "a\n\n\nb", "```\n```", "x **y** z"):
        document = adf.to_adf(source)
        assert document["type"] == "doc" and document["version"] == 1
        assert all(text for text in texts(document)), source
    assert adf.to_adf("")["content"] == []


def test_adf_blocks_and_marks_round_trip_as_text():
    source = "# Plan\n\nFirst line\nsecond line\n\n- one\n- two\n\n3. three\n4. four\n\n> quoted\n\n```py\nx = 1\n```"
    document = adf.to_adf(source)
    kinds = [block["type"] for block in document["content"]]
    assert kinds == ["heading", "paragraph", "bulletList", "orderedList", "blockquote", "codeBlock"]
    assert document["content"][3]["attrs"] == {"order": 3}
    assert document["content"][5]["attrs"] == {"language": "py"}
    text = adf.to_text(document)
    assert "First line\nsecond line" in text and "- one\n- two" in text and "3. three\n4. four" in text
    assert "x = 1" in text


def test_adf_mentions_links_and_trailing_punctuation():
    document = adf.to_adf("Ask [~accountid:abc:123] about https://x.test/a, or [the doc](https://x.test/b).",
                          mention_names={"abc:123": "Priya"})
    nodes = document["content"][0]["content"]
    mention = next(node for node in nodes if node["type"] == "mention")
    assert mention["attrs"] == {"id": "abc:123", "text": "@Priya"}
    links = [node for node in nodes if any(mark["type"] == "link" for mark in node.get("marks", []))]
    assert [node["marks"][0]["attrs"]["href"] for node in links] == ["https://x.test/a", "https://x.test/b"]
    assert adf.mentioned_account_ids(document) == ["abc:123"]
    assert adf.to_text(document).startswith("Ask @Priya about https://x.test/a, or the doc")


def test_adf_reads_nodes_jira_writes_and_ignores_unknown_ones():
    document = {"type": "doc", "version": 1, "content": [
        {"type": "table", "content": [{"type": "tableRow", "content": [
            {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "a"}]}]},
            {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "b"}]}]}]}]},
        {"type": "mediaSingle", "content": [{"type": "media", "attrs": {"id": "1"}}]},
        {"type": "somethingNew", "content": [{"type": "text", "text": "kept"}]},
        {"type": "paragraph", "content": [{"type": "status", "attrs": {"text": "DONE"}},
                                          {"type": "inlineCard", "attrs": {"url": "https://x.test/c"}}]}]}
    text = adf.to_text(document)
    assert "a | b" in text and "[attachment]" in text and "kept" in text and "[DONE]https://x.test/c" in text
    assert adf.to_text("plain string") == "plain string" and adf.to_text(None) == ""


# ── JQL ────────────────────────────────────────────────────────────────────

def test_jql_quotes_what_a_person_typed():
    query = jql.build(jql.Filters.from_params({"project": "desk", "label": 'x" OR project = SECRET', "text": 'a"b\\'}))
    assert 'labels = "x\\" OR project = SECRET"' in query
    assert 'text ~ "a\\"b\\\\"' in query
    assert query.startswith('project = "DESK" AND ')


def test_jql_is_always_bounded_and_refuses_bad_input():
    assert jql.build(jql.Filters()) == "updated >= -30d ORDER BY updated DESC"
    for bad in ({"project": "a b"}, {"assignee": "Priya Raman"}, {"sprint": "x"}, {"statusCategory": "nope"},
                {"parent": "nokey"}, {"updatedWithinDays": "many"}):
        with pytest.raises(jql.InvalidQuery):
            jql.build(jql.Filters.from_params(bad))
    with pytest.raises(jql.InvalidQuery):
        jql.build(jql.Filters(), order="password")
    for bad in ("", "  ", "order by created", "x" * 5000):
        with pytest.raises(jql.InvalidQuery):
            jql.checked(bad)
    assert jql.checked("  project = A\n  ORDER BY key ") == "project = A ORDER BY key"


def test_jql_an_issue_key_typed_as_text_finds_that_issue():
    assert "key = DESK-12" in jql.build(jql.Filters.from_params({"text": "desk-12"}))


def test_every_named_view_runs_on_the_synthetic_site():
    jira_site = site()
    client = JiraClient(jira_site)
    found = {view.id: [issue["key"] for issue in client.search(jql.view_jql(view.id), fields=["summary"])["issues"]]
             for view in jql.VIEWS}
    assert found["overdue"] == ["OPS-1"]
    assert found["my_approvals"] == ["HELP-1"] and found["mentions"] == ["DESK-4"]
    assert found["blocked"] == ["DESK-4"] and "DESK-5" in found["unassigned"]
    assert found["my_open"][0] == "OPS-1"                       # highest priority first
    narrowed = jql.view_jql("my_open", jql.Filters.from_params({"project": "DESK"}))
    assert all(key.startswith("DESK-") for key in
               (issue["key"] for issue in client.search(narrowed, fields=["summary"])["issues"]))


# ── models ─────────────────────────────────────────────────────────────────

def test_field_map_is_found_by_schema_not_by_name():
    fmap = models.FieldMap.from_fields([
        {"id": "customfield_1", "name": "Iteration", "custom": True, "schema": {"custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
        {"id": "customfield_2", "name": "Story Points", "custom": True, "schema": {"custom": "x:float"}},
        {"id": "customfield_3", "name": "Story point estimate", "custom": True,
         "schema": {"custom": "com.pyxis.greenhopper.jira:jsw-story-points"}},
        {"id": "summary", "name": "Sprint", "custom": False}])
    assert fmap.sprint == "customfield_1" and fmap.story_points == ("customfield_2", "customfield_3")


def test_issue_view_is_flat_and_carries_no_email():
    jira_site = site()
    ctx = context(jira_site)
    raw = ctx.client.get_issue("DESK-4", fields=[*models.DETAIL_FIELDS, *ctx.field_map.ids()],
                               expand="transitions,changelog,editmeta")
    raw["fields"]["assignee"]["emailAddress"] = "tomas@example.test"
    view = models.issue_view(raw, site_url=jira_site.site_url, field_map=ctx.field_map, now=NOW, me="sbx-me",
                             detail=True)
    assert view["url"] == "https://desk-sandbox.jira.example/browse/DESK-4"
    assert view["status"] == {"id": "10003", "name": "Blocked", "category": "in_progress"}
    assert view["sprint"]["name"] == "Sprint 8" and view["storyPoints"] == 3 and view["flagged"] is True
    assert view["signals"]["overdue"] and view["signals"]["blocked"] and view["signals"]["dueInDays"] == -2
    assert view["comments"][0]["mentionsMe"] is True
    assert [link["label"] for link in view["links"]] == ["is blocked by"] and view["links"][0]["blocksThis"]
    assert {transition["to"]["name"] for transition in view["transitions"]} == {"To Do", "In Progress", "In Review", "Done"}
    assert "example.test" not in json.dumps(view)


def test_jira_timestamps_parse():
    assert models.parse_instant("2026-11-14T09:30:00.000+0100").utcoffset() == dt.timedelta(hours=1)
    assert models.parse_instant("2026-11-14").date() == dt.date(2026, 11, 14)
    assert models.parse_instant("nonsense") is None and models.parse_instant(None) is None


def test_page_of_reports_more_for_both_paging_styles():
    assert models.page_of([1, 2], next_page_token="t")["more"] is True
    assert models.page_of([1, 2], is_last=True)["more"] is False
    offset = models.page_of([1, 2], start_at=0, total=5)
    assert offset["more"] is True and offset["nextStartAt"] == 2
    assert models.page_of([1, 2], start_at=3, total=5)["more"] is False


# ── insights ───────────────────────────────────────────────────────────────

def _rows(jira_site, query="updated >= -90d ORDER BY updated DESC"):
    ctx = context(jira_site)
    page = ctx.client.search(query, fields=[*models.LIST_FIELDS, "issuelinks", *ctx.field_map.ids()])
    return ctx, [models.issue_view(raw, site_url=jira_site.site_url, field_map=ctx.field_map, now=NOW)
                 for raw in page["issues"]]


def test_digest_lists_each_issue_once_in_its_most_pressing_section():
    _, rows = _rows(site())
    result = insights.digest(rows, me="sbx-me")
    listed = [issue["key"] for section in result["sections"] for issue in section["issues"]]
    assert len(listed) == len(set(listed))
    by_id = {section["id"]: [issue["key"] for issue in section["issues"]] for section in result["sections"]}
    assert by_id["overdue"] == ["DESK-4", "OPS-1"] and "DESK-6" in by_id["stale"]
    assert result["counts"]["blocked"] == 1 and result["complete"] is True
    assert insights.digest(rows, complete=False)["complete"] is False


def test_sprint_health_compares_work_done_with_time_gone():
    jira_site = site()
    ctx = context(jira_site)
    sprint = models.sprint_view(ctx.client.sprint(2))
    rows = [models.issue_view(raw, field_map=ctx.field_map, now=NOW) for raw in
            ctx.client.sprint_issues(2, fields=[*models.LIST_FIELDS, *ctx.field_map.ids()])["issues"]]
    health_ = insights.sprint_health(sprint, rows, now=NOW)
    assert health_["measuredIn"] == "points" and health_["percentElapsed"] == 64 and health_["percentDone"] == 22
    assert health_["atRisk"] and health_["blocked"] == ["DESK-4"] and health_["daysLeft"] == 5
    done = [{**row, "status": {"name": "Done", "category": "done"}, "signals": {}} for row in rows]
    assert insights.sprint_health(sprint, done, now=NOW)["atRisk"] is False
    assert insights.workload(rows)[0]["open"] >= insights.workload(rows)[-1]["open"]


# ── transport and client ───────────────────────────────────────────────────

class Reply:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
        self.content = b"" if body is None else b"x"
        self.text = "" if body is None else str(body)

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


def scripted(*replies):
    sent, queue = [], list(replies)

    def send(method, url, **kwargs):
        sent.append({"method": method, "url": url, **kwargs})
        return queue.pop(0)
    return send, sent


def test_transport_goes_through_the_gateway_and_never_without_a_token():
    assert url_for("c1", "agile", "/board/3") == f"{GATEWAY}/ex/jira/c1/rest/agile/1.0/board/3"
    assert set(API_ROOTS) == {"platform", "agile", "software", "servicedesk"}
    send, sent = scripted(Reply(200, {"ok": True}), Reply(204))
    transport = GatewayTransport(cloud_id="c1", token=lambda: "tok", send=send)
    assert transport.request("GET", "platform", "myself", params={"a": None, "b": 1}).body == {"ok": True}
    assert sent[0]["headers"]["Authorization"] == "Bearer tok" and sent[0]["params"] == {"b": 1}
    transport.request("POST", "platform", "issue/A-1/attachments", files={"file": ("a.txt", b"x", "text/plain")})
    assert sent[1]["headers"]["X-Atlassian-Token"] == "no-check" and "Content-Type" not in sent[1]["headers"]

    silent, nothing_sent = scripted()
    client = JiraClient(GatewayTransport(cloud_id="c1", token=lambda: None, send=silent))
    with pytest.raises(JiraError) as refused:
        client.myself()
    assert refused.value.code == "reconnect_required" and nothing_sent == []


def test_gateway_refusal_is_told_apart_from_a_resource_error_and_a_missing_scope():
    assert gateway_refused(JiraResponse(404, {"message": "No message available", "path": "/ex/jira/x"}))
    assert gateway_refused(JiraResponse(401, {"message": "Unauthorized"}))
    assert not gateway_refused(JiraResponse(404, {"errorMessages": ["Issue does not exist"], "errors": {}}))
    scope = JiraResponse(401, {"code": 401, "message": "Unauthorized; scope does not match"})
    assert scope_refused(scope) and not gateway_refused(scope)


def _client(*replies):
    send, sent = scripted(*replies)
    waits = []
    return JiraClient(GatewayTransport(cloud_id="c1", token=lambda: "tok", send=send), sleep=waits.append), sent, waits


def test_client_maps_errors_to_codes_and_never_passes_the_upstream_body_on():
    cases = [
        (Reply(401, {"message": "Unauthorized; scope does not match"}), "scope_missing"),
        (Reply(401, {"message": "Unauthorized"}), "reconnect_required"),
        (Reply(404, {"errorMessages": ["Issue does not exist"], "errors": {}}), "not_found"),
        (Reply(403, {"errorMessages": ["You do not have permission"], "errors": {}}), "forbidden"),
        (Reply(400, {"errorMessages": [], "errors": {"summary": "required"}}), "invalid_request"),
        (Reply(503, "<html>secret stack trace</html>"), "jira_unavailable"),
    ]
    for reply, code in cases:
        client, _, _ = _client(reply)
        with pytest.raises(JiraError) as caught:
            client.get_issue("A-1")
        assert caught.value.code == code
        assert "secret" not in caught.value.message
    client, _, _ = _client(Reply(400, {"errorMessages": [], "errors": {"summary": "required"}}))
    with pytest.raises(JiraError) as caught:
        client.create_issue({})
    assert caught.value.fields == {"summary": "required"}


def test_client_waits_once_on_a_short_429_and_gives_up_on_a_long_one():
    client, sent, waits = _client(Reply(429, {}, {"Retry-After": "2", "X-RateLimit-Remaining": "0",
                                                  "RateLimit-Reason": "jira-burst-based"}),
                                  Reply(200, {"accountId": "a"}))
    assert client.myself() == {"accountId": "a"} and waits == [2.0] and len(sent) == 2
    client, sent, waits = _client(Reply(429, {}, {"Retry-After": "600"}))
    with pytest.raises(JiraError) as caught:
        client.myself()
    assert caught.value.code == "rate_limited" and caught.value.retry_after == 600 and waits == []
    assert len(sent) == 1
    client, sent, waits = _client(Reply(429, {}, {"Retry-After": "1"}), Reply(429, {}, {"Retry-After": "1"}))
    with pytest.raises(JiraError):
        client.myself()
    assert len(sent) == 2                                     # never a third attempt


def test_client_uses_the_current_search_and_listing_endpoints():
    client, sent, _ = _client(Reply(200, {"issues": [], "isLast": True}), Reply(200, {"count": 3}),
                              Reply(404, {"message": "No message available", "errorMessages": []}),
                              Reply(200, {"issues": [], "total": 0}), Reply(204), Reply(204))
    client.search("project = A", fields=["summary"], next_page_token="t")
    assert sent[0]["url"].endswith("/rest/api/3/search/jql") and sent[0]["method"] == "POST"
    assert sent[0]["json"] == {"jql": "project = A", "fields": ["summary"], "maxResults": 50, "nextPageToken": "t"}
    assert client.count("project = A") == 3 and sent[1]["url"].endswith("/search/approximate-count")
    client.sprint_issues(7)                                    # the new path, then the old one on 404
    assert sent[2]["url"].endswith("/rest/software/1.0/sprint/7/issue")
    assert sent[3]["url"].endswith("/rest/agile/1.0/sprint/7/issue")
    client.add_watcher("A-1", "acc")
    assert sent[4]["json"] == "acc"                            # a bare JSON string
    client.assign("A-1", None)
    assert sent[5]["json"] == {"accountId": None}
    assert not hasattr(client, "delete_issue")


# ── actions ────────────────────────────────────────────────────────────────

def test_every_action_is_described_and_needs_a_known_scope_group():
    names = [action.name for action in actions.ACTIONS]
    assert len(names) == len(set(names)) and "delete_issue" not in names
    for action in actions.ACTIONS:
        assert action.needs in policy.GROUP_BY_ID and policy.GROUP_BY_ID[action.needs].write
        assert action.risk in ("low", "medium", "high") and action.describe()["params"]


def test_clean_reports_every_problem_at_once():
    with pytest.raises(actions.InvalidAction) as caught:
        actions.ACTION_BY_NAME["create_issue"].clean(
            {"project": "bad key", "summary": " ", "labels": ["two words"], "dueDate": "soon",
             "assignee": "Priya Raman", "storyPoints": "many"})
    assert {problem["field"] for problem in caught.value.problems} == {
        "project", "summary", "labels", "dueDate", "assignee", "storyPoints"}
    with pytest.raises(actions.InvalidAction):
        actions.ACTION_BY_NAME["edit_issue"].clean({"issue": "DESK-1"})        # nothing to change
    with pytest.raises(actions.InvalidAction):
        actions.ACTION_BY_NAME["link_issues"].clean({"issue": "DESK-1", "otherIssue": "desk-1"})


def test_durations():
    assert actions.parse_duration("1h 30m") == 5400 and actions.parse_duration("2d") == 57600
    assert actions.parse_duration("90") == 90 and actions.parse_duration(1.0) == 1
    for bad in ("", None, "soon", "1h x", 0, True, "-1h"):
        assert actions.parse_duration(bad) is None
    assert actions.format_duration(5400) == "1h 30m"


def test_transition_matching_refuses_to_guess():
    transitions = [{"id": "1", "name": "Start progress", "to": {"name": "In Progress"}},
                   {"id": "2", "name": "Start review", "to": {"name": "In Review"}}]
    assert actions.match_transition(transitions, "2")[0]["id"] == "2"
    assert actions.match_transition(transitions, "in review")[0]["id"] == "2"
    chosen, names, ambiguous = actions.match_transition(transitions, "start")
    assert chosen is None and ambiguous and names == ["Start progress", "Start review"]
    assert actions.match_transition(transitions, "done") == (None, ["Start progress", "Start review"], False)


# ── proposals ──────────────────────────────────────────────────────────────

SANDBOX = policy.writes({}, sandbox=True)
HELD = policy.writes({}, sandbox=False)
EXTERNAL = policy.writes(WRITES_ON, sandbox=False)


def desk():
    return proposals.ProposalDesk(clock=lambda: NOW)


def test_policy_holds_real_writes_until_both_switches_are_set():
    assert HELD["mode"] == "held" and HELD["reason"] == "jira_writes_switch"
    assert policy.writes({"DESK_JIRA_WRITES": "on"}, sandbox=False)["reason"] == "jira_writes_authorized_by"
    assert EXTERNAL["mode"] == "external" and SANDBOX["mode"] == "sandbox" and SANDBOX["simulated"]
    assert not policy.is_on({}) and policy.is_on(ON)


def test_proposing_reads_and_writes_nothing():
    jira_site = site()
    ctx = context(jira_site)
    proposal = desk().propose(User, ctx, "transition_issue", {"issue": "desk-5", "transition": "in progress"},
                              scopes=[], simulated=True)
    assert proposal["status"] == "awaiting_approval"
    assert proposal["summary"] == ("Move DESK-5 (Time zone data for the availability service) "
                                   "from To Do to In Progress.")
    assert proposal["before"]["status"]["name"] == "To Do" and proposal["to"]["name"] == "In Progress"
    assert "_transitionId" not in proposal["input"]
    assert jira_site.log == [] and jira_site.issues["DESK-5"]["fields"]["status"]["name"] == "To Do"


def test_an_approved_proposal_runs_once_and_is_read_back():
    jira_site = site()
    ctx, board = context(jira_site), desk()
    proposal = board.propose(User, ctx, "transition_issue", {"issue": "DESK-5", "transition": "Done",
                                                             "resolution": "Won't Do", "comment": "Not needed."},
                             scopes=[], simulated=True)
    done = board.approve(User, ctx, proposal["id"], writes=SANDBOX)
    assert done["status"] == "executed" and done["verification"]["verified"] is True
    assert done["decidedBy"] == EXEC and done["simulated"] is True
    assert jira_site.issues["DESK-5"]["fields"]["resolution"] == {"name": "Won't Do"}
    assert [event["kind"] for event in done["events"]] == ["proposed", "approved", "executed", "verified"]
    with pytest.raises(proposals.ProposalConflict) as again:
        board.approve(User, ctx, proposal["id"], writes=SANDBOX)
    assert again.value.code == "already_decided"
    assert len([entry for entry in jira_site.log if entry["op"] == "issue.transition"]) == 1


def test_held_means_nothing_is_sent_and_it_can_be_approved_later():
    jira_site = site()
    ctx, board = context(jira_site), desk()
    proposal = board.propose(User, ctx, "add_comment", {"issue": "DESK-1", "body": "Looks good."},
                             scopes=policy.recommended_scopes(), simulated=False)
    before = jira_site.requests
    held = board.approve(User, ctx, proposal["id"], writes=HELD)
    assert held["status"] == "awaiting_approval" and held["held"]["code"] == "jira_writes_disabled"
    assert jira_site.requests == before and jira_site.log == []
    assert board.approve(User, ctx, proposal["id"], writes=EXTERNAL)["status"] == "executed"


def test_a_proposal_never_changes_worlds_between_proposal_and_approval():
    jira_site = site()
    ctx, board = context(jira_site), desk()
    simulated = board.propose(User, ctx, "watch_issue", {"issue": "DESK-9"}, scopes=[], simulated=True)
    with pytest.raises(proposals.ProposalConflict) as caught:
        board.approve(User, ctx, simulated["id"], writes=EXTERNAL)
    assert caught.value.code == "world_changed" and jira_site.log == []


def test_an_issue_that_moved_on_is_not_transitioned():
    jira_site = site()
    ctx, board = context(jira_site), desk()
    proposal = board.propose(User, ctx, "transition_issue", {"issue": "DESK-5", "transition": "In Progress"},
                             scopes=[], simulated=True)
    ctx.client.transition("DESK-5", "41")                      # somebody blocks it meanwhile
    result = board.approve(User, ctx, proposal["id"], writes=SANDBOX)
    assert result["status"] == "failed" and result["error"]["code"] == "issue_changed"
    assert jira_site.issues["DESK-5"]["fields"]["status"]["name"] == "Blocked"


def test_an_unknown_outcome_is_not_retried_until_the_person_checked():
    jira_site = site()
    ctx, board = context(jira_site), desk()
    proposal = board.propose(User, ctx, "log_work", {"issue": "DESK-2", "timeSpent": "30m"}, scopes=[], simulated=True)
    jira_site.fail_next(503)
    result = board.approve(User, ctx, proposal["id"], writes=SANDBOX)
    assert result["status"] == "outcome_unknown"
    with pytest.raises(proposals.ProposalConflict) as caught:
        board.approve(User, ctx, proposal["id"], writes=SANDBOX)
    assert caught.value.code == "confirm_checked"
    assert board.approve(User, ctx, proposal["id"], writes=SANDBOX, confirmed=True)["status"] == "executed"


def test_a_refused_write_fails_and_a_rejection_writes_nothing():
    jira_site = site()
    ctx, board = context(jira_site), desk()
    proposal = board.propose(User, ctx, "assign_issue", {"issue": "DESK-5", "assignee": "sbx-aiko"},
                             scopes=[], simulated=True)
    jira_site.fail_next(403)
    failed = board.approve(User, ctx, proposal["id"], writes=SANDBOX)
    assert failed["status"] == "failed" and failed["error"]["code"] == "forbidden"
    other = board.propose(User, ctx, "assign_issue", {"issue": "DESK-5", "assignee": "sbx-aiko"},
                          scopes=[], simulated=True)
    assert other["id"] != proposal["id"]
    assert board.reject(User, other["id"])["status"] == "rejected" and jira_site.log == []
    with pytest.raises(proposals.ProposalConflict):
        board.approve(User, ctx, other["id"], writes=SANDBOX)


def test_the_same_change_asked_twice_is_one_proposal_and_scopes_are_checked():
    ctx, board = context(site()), desk()
    first = board.propose(User, ctx, "watch_issue", {"issue": "DESK-9"}, scopes=[], simulated=True)
    assert board.propose(User, ctx, "watch_issue", {"issue": "desk-9"}, scopes=[], simulated=True)["id"] == first["id"]
    with pytest.raises(JiraError) as caught:
        board.propose(User, ctx, "move_to_sprint", {"sprint": 3, "issues": ["DESK-10"]},
                      scopes=["read:jira-work", "write:jira-work"], simulated=False)
    assert caught.value.code == "scope_missing" and "write:sprint:jira-software" in caught.value.message
    with pytest.raises(actions.InvalidAction):
        board.propose(User, ctx, "delete_issue", {"issue": "DESK-1"}, scopes=[], simulated=True)


@pytest.mark.parametrize("name,payload,op", [
    ("create_issue", {"project": "DESK", "summary": "New", "issueType": "bug", "assignee": "me",
                      "parent": "DESK-1", "dueDate": "2026-11-20", "storyPoints": 2, "labels": ["a"]}, "issue.create"),
    ("edit_issue", {"issue": "OPS-1", "dueDate": "2026-11-18", "addLabels": ["urgent"], "priority": "High"}, "issue.edit"),
    ("assign_issue", {"issue": "DESK-5", "assignee": None}, "issue.assign"),
    ("add_comment", {"issue": "DESK-4", "body": "[~accountid:sbx-tomas] on it."}, "comment.add"),
    ("log_work", {"issue": "DESK-2", "timeSpent": "1h 30m", "started": "2026-11-15"}, "worklog.add"),
    ("link_issues", {"issue": "DESK-9", "otherIssue": "DESK-2", "linkType": "is blocked by"}, "issue.link"),
    ("unwatch_issue", {"issue": "DESK-4"}, "issue.unwatch"),
    ("move_to_sprint", {"sprint": 3, "issues": ["DESK-10"]}, "sprint.move"),
    ("move_to_backlog", {"issues": ["DESK-9"]}, "sprint.move"),
    ("rank_issues", {"issues": ["DESK-10"], "before": "DESK-2"}, "issue.rank"),
    ("create_sprint", {"board": 1, "name": "Sprint 10"}, "sprint.create"),
    ("complete_sprint", {"sprint": 2}, "sprint.update"),
    ("create_version", {"project": "DESK", "name": "1.5", "releaseDate": "2026-12-20"}, "version.create"),
    ("answer_approval", {"issue": "HELP-1", "approval": 1, "decision": "approve"}, "approval.answer"),
])
def test_each_action_runs_against_the_synthetic_site(name, payload, op):
    jira_site = site()
    ctx, board = context(jira_site), desk()
    proposal = board.propose(User, ctx, name, payload, scopes=[], simulated=True)
    assert proposal["summary"].endswith(".") and jira_site.log == []
    result = board.approve(User, ctx, proposal["id"], writes=SANDBOX)
    assert result["status"] == "executed", result["error"]
    assert (result["verification"] or {}).get("verified") is not False
    assert jira_site.log[-1]["op"] == op


def test_what_the_project_or_the_workflow_does_not_allow_is_refused_when_proposing():
    jira_site = site()
    ctx, board = context(jira_site), desk()
    for name, payload, field_name in [
        ("create_issue", {"project": "DESK", "summary": "x", "issueType": "Incident"}, "issueType"),
        ("create_issue", {"project": "DESK", "summary": "x", "issueType": "Sub-task"}, "parent"),
        ("transition_issue", {"issue": "DESK-5", "transition": "To Do"}, "transition"),
        ("link_issues", {"issue": "DESK-1", "otherIssue": "DESK-2", "linkType": "Clones"}, "linkType"),
        ("assign_issue", {"issue": "DESK-5", "assignee": "nobody-here"}, "assignee"),
        ("start_sprint", {"sprint": 2, "endDate": "2026-12-01"}, "sprint"),
        ("complete_sprint", {"sprint": 3}, "sprint"),
        ("move_to_sprint", {"sprint": 1, "issues": ["DESK-10"]}, "sprint"),
    ]:
        with pytest.raises(actions.InvalidAction) as caught:
            board.propose(User, ctx, name, payload, scopes=[], simulated=True)
        assert caught.value.problems[0]["field"] == field_name, name
    with pytest.raises(JiraError) as missing:
        board.propose(User, ctx, "add_comment", {"issue": "DESK-999", "body": "x"}, scopes=[], simulated=True)
    assert missing.value.code == "not_found" and jira_site.log == []


# ── features ───────────────────────────────────────────────────────────────

def test_the_feature_map_is_consistent_with_the_actions_and_the_scopes():
    rows = features.catalogue(["read:jira-work", "read:jira-user", "write:jira-work", "offline_access"])
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)) and sum(features.summary(rows).values()) == len(rows)
    by_id = {row["id"]: row for row in rows}
    assert by_id["my_open"]["granted"] and not by_id["boards"]["granted"]
    assert "read:board-scope:jira-software" in by_id["boards"]["missingScopes"]
    for feature_id in ("projects", "project_detail", "components"):
        assert by_id[feature_id]["needs"] == "projects_read" and not by_id[feature_id]["granted"]
        assert by_id[feature_id]["missingScopes"] == ["read:project:jira"]
    assert all(row["write"] is False for row in rows if row["needs"] == "projects_read")
    with_projects = {row["id"]: row for row in features.catalogue(
        ["read:jira-work", "read:project:jira"])}
    assert with_projects["projects"]["granted"] and with_projects["project_detail"]["granted"]
    for row in rows:
        if (row["route"] or "").startswith("action "):
            assert row["route"].split()[1] in actions.ACTION_BY_NAME, row["id"]
        if row["state"] == "excluded":
            assert row["note"]
    assert all(row["granted"] for row in features.catalogue([], simulated=True))
    assert len(policy.recommended_scopes(servicedesk=True, admin=True, webhooks=True)) < 50


def test_the_project_read_scope_is_recommended_read_only_and_reported():
    scopes = policy.recommended_scopes(software=False)
    assert "read:project:jira" in scopes and len(scopes) == len(set(scopes))
    assert "read:project:jira" in policy.recommended_scopes()
    group = policy.GROUP_BY_ID["projects_read"]
    assert not group.write and not group.optional and group.product == "jira"
    report = {row["id"]: row for row in policy.scope_report(["read:jira-work"])}
    assert not report["projects_read"]["granted"] and report["projects_read"]["missing"] == ["read:project:jira"]
    assert policy.allows("read:jira-work read:project:jira", "projects_read")
    assert not any(action.needs == "projects_read" for action in actions.ACTIONS)


# ── routes ─────────────────────────────────────────────────────────────────

class JiraGateway(FakeGateway):
    """The fake gateway plus what ``ScribaGateway`` offers for Jira."""

    def __init__(self):
        super().__init__()
        self.connection = {"configured": False, "missingEnv": ["JIRA_CLIENT_ID", "JIRA_CLIENT_SECRET"],
                           "redirectUri": None, "publicApiBase": "https://desk.example/api",
                           "requestedScopes": ["read:jira-work"], "connected": False, "hasAccount": False}
        self.live = site()
        self.audited = []

    def connect(self, scopes=None):
        self.connection.update({"configured": True, "missingEnv": [], "hasAccount": True, "connected": True,
                                "cloudId": "c1", "siteName": "Acme", "siteUrl": "https://acme.atlassian.example",
                                "accountId": "sbx-me", "displayName": "Exec",
                                "scopes": scopes or policy.recommended_scopes(servicedesk=True, admin=True)})

    def jira_connection(self, user):
        return dict(self.connection)

    def jira_token(self, user):
        return "tok" if self.connection.get("connected") else None

    def jira_send(self):
        prefix = f"{GATEWAY}/ex/jira/c1"

        def send(method, url, params=None, json=None, files=None, headers=None, timeout=None):
            assert url.startswith(prefix) and headers["Authorization"] == "Bearer tok"
            rest = url[len(prefix):]
            api = next(name for name, root in API_ROOTS.items() if rest.startswith(root + "/"))
            response = self.live.request(method, api, rest[len(API_ROOTS[api]) + 1:], params=params, json=json)
            return Reply(response.status, response.body, dict(response.headers))
        return send

    def audit(self, user, action, entity_id, details):
        self.audited.append((user.email, action, entity_id))


def app_for(env, *, sandbox=False):
    gateway = JiraGateway()
    gateway.add_user(1, EXEC)
    gateway.add_user(2, OTHER)
    registry = WorldRegistry()
    if sandbox:
        world = SandboxWorld("w1", owner_email=EXEC)
        world.set_now(NOW)
        registry.add(world, default=True)
    app = FastAPI()
    router = build_jira_router(RoutedGateway(gateway, registry), env=env, clock=lambda: NOW)
    app.include_router(router)
    return gateway, TestClient(app), router.jira


def call(client, method, path, user=EXEC, **kwargs):
    return client.request(method, path, headers={"x-test-user": user} if user else {}, **kwargs)


def test_with_jira_off_only_status_answers_and_health_does_not_name_it():
    _, client, _ = app_for({})
    assert call(client, "GET", "/desk/jira/status").json() == {"enabled": False, "version": "0.1.0"}
    for path in ("/desk/jira/issues", "/desk/jira/briefing", "/desk/jira/features", "/desk/jira/proposals"):
        assert call(client, "GET", path).status_code == 404
    assert call(client, "POST", "/desk/jira/proposals", json={"action": "watch_issue", "input": {}}).status_code == 404
    assert health({}) == {} and health(ON)["jira"]["writes"] == "held"


def test_every_route_requires_a_session():
    _, client, _ = app_for(ON)
    for path in ("/desk/jira/status", "/desk/jira/issues", "/desk/jira/briefing", "/desk/jira/proposals"):
        assert call(client, "GET", path, user=None).status_code == 401
    assert call(client, "POST", "/desk/jira/proposals/jp-1/approve", user=None).status_code == 401


def test_status_explains_what_is_missing_without_any_secret():
    gateway, client, _ = app_for(ON)
    body = call(client, "GET", "/desk/jira/status").json()
    assert body["state"] == "not_configured" and body["connected"] is False
    assert body["setup"]["missingEnv"] == ["JIRA_CLIENT_ID", "JIRA_CLIENT_SECRET"]
    assert body["setup"]["callbackUrl"] == "https://desk.example/api/auth/jira/callback"
    assert "read:board-scope:jira-software" in body["setup"]["scopesToAdd"]
    assert body["writes"]["mode"] == "held" and body["proposals"] == {"waiting": 0, "kind": "memory", "durable": False}
    # Not ready is a 409 with a code, never a 401: a 401 means the Scriba session is gone.
    refused = call(client, "GET", "/desk/jira/issues")
    assert refused.status_code == 409 and refused.json()["errorCode"] == "not_configured"
    gateway.connection.update({"configured": True, "missingEnv": []})
    assert call(client, "GET", "/desk/jira/issues").json()["errorCode"] == "not_connected"
    gateway.connection.update({"hasAccount": True, "cloudId": "c1"})
    assert call(client, "GET", "/desk/jira/status").json()["state"] == "reconnect_required"
    assert call(client, "GET", "/desk/jira/issues").json()["errorCode"] == "reconnect_required"


def test_live_reads_go_through_the_gateway_with_the_persons_token():
    gateway, client, _ = app_for(ON)
    gateway.connect()
    status = call(client, "GET", "/desk/jira/status").json()
    assert status["state"] == "connected" and status["mode"] == "live" and status["site"]["name"] == "Acme"
    page = call(client, "GET", "/desk/jira/issues", params={"view": "my_open", "limit": 2, "count": "true"}).json()
    assert [issue["key"] for issue in page["issues"]] == ["OPS-1", "DESK-1"]
    assert page["page"]["more"] and page["approximateCount"] == 5 and page["simulated"] is False
    assert page["issues"][0]["url"] == "https://acme.atlassian.example/browse/OPS-1"
    more = call(client, "GET", "/desk/jira/issues", params={"view": "my_open", "limit": 2,
                                                            "pageToken": page["page"]["nextPageToken"]}).json()
    assert [issue["key"] for issue in more["issues"]] == ["DESK-2", "DESK-9"]
    detail = call(client, "GET", "/desk/jira/issues/desk-4").json()["issue"]
    assert detail["description"].startswith("A meeting proposed") and detail["transitions"] and detail["editable"]
    assert call(client, "GET", "/desk/jira/issues/DESK-999").status_code == 404
    assert call(client, "GET", "/desk/jira/issues/not-a-key").json()["errorCode"] == "invalid_query"
    assert call(client, "GET", "/desk/jira/issues", params={"jql": "ORDER BY created"}).status_code == 400
    assert call(client, "GET", "/desk/jira/issues", params={"project": "a b"}).status_code == 400


def test_the_read_routes_answer_in_the_desks_shapes():
    gateway, client, _ = app_for(ON)
    gateway.connect()
    get = lambda path, **params: call(client, "GET", path, params=params)       # noqa: E731
    assert [p["key"] for p in get("/desk/jira/projects").json()["projects"]] == ["DESK", "OPS", "HELP"]
    project = get("/desk/jira/projects/desk").json()
    assert {kind["name"] for kind in project["issueTypes"]} >= {"Task", "Bug", "Epic"}
    fields = get("/desk/jira/projects/DESK/create-fields", issueType="Task").json()["fields"]
    assert next(row for row in fields if row["id"] == "priority")["allowedValues"][0] == "Highest"
    releases = get("/desk/jira/projects/DESK/releases").json()["releases"]
    open_release = next(row for row in releases if row["version"]["name"] == "1.4")
    assert open_release["progress"] == {"total": 6, "done": 2, "open": 4, "percentDone": 33} and open_release["atRisk"]
    assert get("/desk/jira/filters").json()["filters"][0]["name"] == "Release 1.4, still open"
    assert len(get("/desk/jira/filters/10010/issues").json()["issues"]) == 4
    assert get("/desk/jira/dashboards").json()["dashboards"][0]["name"] == "Team overview"
    boards = get("/desk/jira/boards").json()["boards"]
    assert [(board["id"], board["type"]) for board in boards] == [(1, "scrum"), (2, "kanban")]
    board = get("/desk/jira/boards/1").json()
    assert board["activeSprint"]["sprint"]["name"] == "Sprint 8" and board["activeSprint"]["atRisk"]
    assert [column["name"] for column in board["columns"]] == ["To Do", "In Progress", "In Review", "Done"]
    assert {issue["key"] for issue in get("/desk/jira/boards/2").json()["issues"]} == {"OPS-1", "OPS-2", "OPS-3"}
    assert [issue["key"] for issue in get("/desk/jira/boards/1/backlog").json()["issues"]] == ["DESK-10"]
    assert get("/desk/jira/sprints/3").json()["sprint"]["state"] == "future"
    assert get("/desk/jira/sprints/99").status_code == 404
    assert get("/desk/jira/approvals").json()["approvals"][0]["issue"] == "HELP-1"
    assert get("/desk/jira/issues/DESK-4/comments").json()["comments"][0]["mentionsMe"]
    assert get("/desk/jira/issues/DESK-4/history").json() == {"history": []}
    people = get("/desk/jira/people", issue="DESK-4", query="pri").json()
    assert [person["displayName"] for person in people["people"]] == ["Priya Raman"] and people["me"] == "sbx-me"
    listing = get("/desk/jira/features").json()
    assert listing["connected"] and len(listing["actions"]) == len(actions.ACTIONS)


def test_a_connection_without_the_software_scopes_says_which_to_add():
    gateway, client, _ = app_for(ON)
    gateway.connect(scopes=["read:jira-work", "read:jira-user", "write:jira-work", "offline_access"])
    refused = call(client, "GET", "/desk/jira/boards")
    assert refused.status_code == 403 and refused.json()["errorCode"] == "scope_missing"
    assert "read:board-scope:jira-software" in refused.json()["detail"]
    assert call(client, "GET", "/desk/jira/issues", params={"view": "my_sprint"}).status_code == 403
    briefing = call(client, "GET", "/desk/jira/briefing").json()
    assert briefing["counts"]["overdue"] == 2 and briefing["sprints"] == [] and briefing["approvals"] is None


def test_project_reads_need_the_project_scope():
    gateway, client, _ = app_for(ON)
    gateway.connect(scopes=["read:jira-work", "read:jira-user", "write:jira-work", "offline_access"])
    for path in ("/desk/jira/projects", "/desk/jira/projects/DESK"):
        refused = call(client, "GET", path)
        assert refused.status_code == 403 and refused.json()["errorCode"] == "scope_missing", path
        assert "read:project:jira" in refused.json()["detail"]
    assert call(client, "GET", "/desk/jira/issues", params={"view": "my_open"}).status_code == 200
    coverage = {row["id"]: row for row in call(client, "GET", "/desk/jira/features").json()["features"]}
    assert coverage["projects"]["missingScopes"] == ["read:project:jira"]

    gateway.connect(scopes=["read:jira-work", "read:jira-user", "offline_access", "read:project:jira"])
    assert [p["key"] for p in call(client, "GET", "/desk/jira/projects").json()["projects"]] == ["DESK", "OPS", "HELP"]
    assert call(client, "GET", "/desk/jira/projects/DESK").json()["project"]["key"] == "DESK"
    status = call(client, "GET", "/desk/jira/status").json()
    assert {row["id"]: row for row in status["scopes"]}["projects_read"]["granted"]


def test_the_briefing_survives_a_part_that_fails():
    gateway, client, _ = app_for(ON)
    gateway.connect()
    whole = call(client, "GET", "/desk/jira/briefing").json()
    assert whole["unavailable"] == [] and whole["sprints"][0]["sprint"]["name"] == "Sprint 8"
    assert whole["approvals"][0]["issue"] == "HELP-1" and "issues" not in whole["sprints"][0]
    gateway.live.fail_next(500)
    partial = call(client, "GET", "/desk/jira/briefing").json()
    assert partial["unavailable"][0]["part"] == "mine" and partial["counts"]["open"] > 0


def test_live_writes_are_held_until_switched_on_then_audited():
    gateway, client, _ = app_for(ON)
    gateway.connect()
    body = {"action": "transition_issue", "input": {"issue": "DESK-5", "transition": "In Progress"},
            "reason": "Priya asked for it"}
    proposal = call(client, "POST", "/desk/jira/proposals", json=body).json()
    assert proposal["status"] == "awaiting_approval" and proposal["reason"] == "Priya asked for it"
    assert proposal["simulated"] is False
    held = call(client, "POST", f"/desk/jira/proposals/{proposal['id']}/approve").json()
    assert held["status"] == "awaiting_approval" and held["held"]["code"] == "jira_writes_disabled"
    assert gateway.live.log == []
    assert call(client, "GET", "/desk/jira/proposals", params={"status": "open"}).json()["waiting"] == 1

    gateway, client, _ = app_for(WRITES_ON)
    gateway.connect()
    proposal = call(client, "POST", "/desk/jira/proposals", json=body).json()
    done = call(client, "POST", f"/desk/jira/proposals/{proposal['id']}/approve").json()
    assert done["status"] == "executed" and done["verification"]["verified"]
    assert gateway.live.issues["DESK-5"]["fields"]["status"]["name"] == "In Progress"
    assert [action for _, action, _ in gateway.audited] == [
        "desk_jira_approved", "desk_jira_executed", "desk_jira_verified"]
    again = call(client, "POST", f"/desk/jira/proposals/{proposal['id']}/approve")
    assert again.status_code == 409 and again.json()["errorCode"] == "already_decided"


def test_proposal_errors_are_shaped_for_the_desk_client():
    gateway, client, _ = app_for(ON)
    gateway.connect()
    invalid = call(client, "POST", "/desk/jira/proposals", json={"action": "create_issue", "input": {"project": "DESK"}})
    assert invalid.status_code == 422 and invalid.json()["errorCode"] == "invalid_action"
    assert invalid.json()["details"]["problems"][0]["field"] == "summary"
    assert call(client, "POST", "/desk/jira/proposals", json={"action": "delete_issue", "input": {}}).status_code == 422
    assert call(client, "POST", "/desk/jira/proposals/jp-404/approve").status_code == 404
    assert call(client, "POST", "/desk/jira/proposals/jp-404/reject").status_code == 404
    gateway.live.fail_next(429, "120")
    limited = call(client, "GET", "/desk/jira/projects")
    assert limited.status_code == 429 and limited.headers["retry-after"] == "120"


def test_one_persons_proposals_are_not_another_persons():
    gateway, client, _ = app_for(WRITES_ON)
    gateway.connect()
    proposal = call(client, "POST", "/desk/jira/proposals",
                    json={"action": "watch_issue", "input": {"issue": "DESK-9"}}).json()
    assert call(client, "GET", f"/desk/jira/proposals/{proposal['id']}", user=OTHER).status_code == 404
    assert call(client, "POST", f"/desk/jira/proposals/{proposal['id']}/approve", user=OTHER).status_code == 404
    assert call(client, "GET", "/desk/jira/proposals", user=OTHER).json()["proposals"] == []
    assert gateway.live.log == []


def test_in_a_sandbox_world_nothing_reaches_the_real_connection():
    gateway, client, service = app_for(WRITES_ON, sandbox=True)
    gateway.connect()                                          # a real connection exists and must be ignored
    status = call(client, "GET", "/desk/jira/status").json()
    assert status["mode"] == "sandbox" and status["writes"]["mode"] == "sandbox" and status["setup"] is None
    assert status["site"]["name"] == "Desk sandbox"
    page = call(client, "GET", "/desk/jira/issues", params={"view": "overdue"}).json()
    assert page["simulated"] is True and [issue["key"] for issue in page["issues"]] == ["OPS-1"]
    proposal = call(client, "POST", "/desk/jira/proposals",
                    json={"action": "add_comment", "input": {"issue": "OPS-1", "body": "Renewing today."}}).json()
    done = call(client, "POST", f"/desk/jira/proposals/{proposal['id']}/approve").json()
    assert done["status"] == "executed" and done["simulated"] is True
    world_site = service.sites.for_world(SandboxWorld("w1", owner_email=EXEC))
    assert [entry["op"] for entry in world_site.log] == ["comment.add"]
    assert gateway.live.requests == 0 and gateway.live.log == [] and gateway.audited == []
    # The other person has no world: they are on the real connection, and see no sandbox data.
    assert call(client, "GET", "/desk/jira/status", user=OTHER).json()["mode"] == "live"
