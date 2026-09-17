"""Tests for Flux Quick Fix client and Flask proxy routes."""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auth import create_jwt  # noqa: E402
from flux_client import (  # noqa: E402
    FluxClient,
    FluxError,
    FluxKeySetupError,
    build_credentials_payload,
    extract_flux_token,
    jira_key_verified,
    mcp_servers_ready,
    missing_flux_keys,
    reset_flux_client_cache_for_tests,
)


class FakeResp:
    def __init__(self, status_code=200, payload=None, headers=None, text=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(self._payload)
        self.cookies = {}

    def json(self):
        return self._payload


READY_MCP = {
    "servers": [
        {"name": "flux-jira-atlassian", "status": "ready", "error": None},
        {"name": "flux-gerrit", "status": "ready", "error": None},
        {"name": "flux-logs", "status": "ready", "error": None},
    ]
}


def _pipeline_transport(calls, *, verify_ok=True, setup_complete=True, extra=None):
    extra = extra or {}

    def transport(method, url, json=None, headers=None, timeout=None):
        calls.append({"method": method, "url": url, "json": json, "headers": headers})
        if url.endswith("/auth/login"):
            return FakeResp(200, {"access_token": "flux-jwt"})
        if url.endswith("/credentials"):
            if method.upper() != "PUT":
                return FakeResp(405, {"detail": "Method Not Allowed"})
            return FakeResp(200, {
                "cursor_api_key": True,
                "gerrit_username": True,
                "gerrit_http_password": True,
                "setup_complete": setup_complete,
                "warnings": [],
            })
        if url.endswith("/mcp-status"):
            return FakeResp(200, READY_MCP)
        if url.endswith("/verify-jira"):
            key = (json or {}).get("keys", ["ENG-1"])[0]
            return FakeResp(200, {"results": {key: verify_ok}})
        if url.endswith("/quick-fix"):
            return FakeResp(200, extra.get("quick_fix") or {
                "record_id": 21,
                "task_id": "task-1",
                "jira_key": (json or {}).get("jira_key"),
                "status": "queued",
            })
        if "/resume" in url:
            return FakeResp(200, extra.get("resume") or {
                "record_id": 21,
                "status": "fixing",
                "message": "Pipeline resumed",
            })
        if "/tickets/" in url:
            return FakeResp(200, extra.get("ticket") or {
                "id": 21,
                "status": "awaiting_review",
                "failure_category": "test_bug",
                "confidence": 0.9,
            })
        return FakeResp(404, {"error": "not found"})

    return transport


class TestFluxHelpers(unittest.TestCase):
    def test_extract_token_shapes(self):
        self.assertEqual(extract_flux_token({"access_token": "abc"}), "abc")
        self.assertEqual(extract_flux_token({"token": "xyz"}), "xyz")
        self.assertEqual(extract_flux_token({"data": {"jwt": "nested"}}), "nested")
        self.assertEqual(
            extract_flux_token({}, {"Authorization": "Bearer hdr"}),
            "hdr",
        )

    def test_missing_keys(self):
        self.assertEqual(missing_flux_keys("", "pw"), "cursor_api_key")
        self.assertEqual(missing_flux_keys("crsr_x", ""), "gerrit_http_password")
        self.assertIsNone(missing_flux_keys("crsr_x", "pw"))

    def test_credentials_payload_uses_login_username(self):
        payload = build_credentials_payload("sudharshan.musali", "crsr_1", "gerrit-pass")
        self.assertEqual(payload["gerrit_username"], "sudharshan.musali")
        self.assertEqual(payload["cursor_api_key"], "crsr_1")
        self.assertEqual(payload["gerrit_http_password"], "gerrit-pass")

    def test_mcp_ready_and_not_ready(self):
        ok, err = mcp_servers_ready(READY_MCP)
        self.assertTrue(ok)
        self.assertEqual(err, "")
        bad, msg = mcp_servers_ready({
            "servers": [{"name": "flux-jira-atlassian", "status": "error", "error": "down"}]
        })
        self.assertFalse(bad)
        self.assertIn("flux-gerrit", msg)

    def test_jira_verify(self):
        self.assertTrue(jira_key_verified({"results": {"ENG-1": True}}, "ENG-1"))
        self.assertFalse(jira_key_verified({"results": {"ENG-1": False}}, "ENG-1"))
        self.assertTrue(jira_key_verified({"results": {"eng-1": True}}, "ENG-1"))


class TestFluxClientPipeline(unittest.TestCase):
    def setUp(self):
        reset_flux_client_cache_for_tests()

    def test_start_quick_fix_puts_credentials_then_queues(self):
        calls = []
        client = FluxClient("alice", "secret", base_url="http://flux.test", transport=_pipeline_transport(calls))
        result = client.start_quick_fix(
            jira_key="ENG-968649",
            target_branch="ganges-7.5-stable",
            log_url=None,
            cursor_api_key="crsr_key",
            gerrit_http_password="gerrit-pass",
        )
        self.assertEqual(result["record_id"], 21)
        self.assertEqual(result["status"], "queued")
        login = next(c for c in calls if c["url"].endswith("/auth/login"))
        self.assertEqual(login["method"], "POST")
        self.assertEqual(login["json"]["username"], "alice")
        creds = next(c for c in calls if c["url"].endswith("/credentials"))
        self.assertEqual(creds["method"], "PUT")
        self.assertEqual(creds["json"]["gerrit_username"], "alice")
        self.assertEqual(creds["json"]["cursor_api_key"], "crsr_key")
        qf = next(c for c in calls if c["url"].endswith("/quick-fix"))
        self.assertEqual(qf["method"], "POST")
        self.assertEqual(qf["json"]["jira_key"], "ENG-968649")
        self.assertEqual(qf["json"]["target_branch"], "ganges-7.5-stable")
        self.assertTrue(qf["json"]["pause_for_review"])
        self.assertIsNone(qf["json"]["log_url"])
        auth_calls = [c for c in calls if c["url"].endswith("/credentials") or c["url"].endswith("/quick-fix")]
        for call in auth_calls:
            self.assertTrue(str(call["headers"].get("Authorization", "")).startswith("Bearer "))

    def test_explicit_log_url_is_forwarded(self):
        calls = []
        client = FluxClient("alice", "secret", base_url="http://flux.test", transport=_pipeline_transport(calls))
        client.start_quick_fix(
            jira_key="ENG-968649",
            target_branch="ganges-7.5-stable",
            log_url="http://logs/example/",
            cursor_api_key="crsr_key",
            gerrit_http_password="gerrit-pass",
        )
        qf = next(c for c in calls if c["url"].endswith("/quick-fix"))
        self.assertEqual(qf["json"]["log_url"], "http://logs/example/")

    def test_credentials_post_is_rejected(self):
        calls = []
        client = FluxClient("alice", "secret", base_url="http://flux.test", transport=_pipeline_transport(calls))
        client.login()
        with self.assertRaises(FluxError) as ctx:
            client._request("POST", "/api/v1/credentials", json_body={"cursor_api_key": "x"})
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(ctx.exception.payload.get("flux_status"), 405)

    def test_verify_jira_false_short_circuits(self):
        calls = []
        client = FluxClient("alice", "secret", base_url="http://flux.test", transport=_pipeline_transport(calls, verify_ok=False))
        with self.assertRaises(FluxError) as ctx:
            client.start_quick_fix(
                jira_key="ENG-1",
                target_branch="master",
                log_url=None,
                cursor_api_key="crsr_key",
                gerrit_http_password="gerrit-pass",
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertTrue(any(c["url"].endswith("/verify-jira") for c in calls))
        self.assertFalse(any(c["url"].endswith("/quick-fix") for c in calls))

    def test_missing_cursor_key(self):
        client = FluxClient("alice", "secret", base_url="http://flux.test", transport=_pipeline_transport([]))
        with self.assertRaises(FluxKeySetupError) as ctx:
            client.start_quick_fix(
                jira_key="ENG-1",
                target_branch="master",
                log_url=None,
                cursor_api_key="",
                gerrit_http_password="pw",
            )
        self.assertTrue(ctx.exception.payload["require_key_setup"])
        self.assertEqual(ctx.exception.payload["missing_key"], "cursor_api_key")

    def test_resume_and_get_ticket(self):
        calls = []
        client = FluxClient("alice", "secret", base_url="http://flux.test", transport=_pipeline_transport(calls))
        ticket = client.get_ticket(21)
        self.assertEqual(ticket["status"], "awaiting_review")
        resumed = client.resume_ticket(21)
        self.assertEqual(resumed["status"], "fixing")
        self.assertTrue(any(c["url"].endswith("/tickets/21") and c["method"] == "GET" for c in calls))
        self.assertTrue(any(c["url"].endswith("/tickets/21/resume") and c["method"] == "POST" for c in calls))


class TestFluxFlaskRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_flask as tf
        cls.tf = tf
        cls.client = tf.app.test_client()

    def setUp(self):
        reset_flux_client_cache_for_tests()
        self.token = create_jwt("alice", "Alice", "alice@nutanix.com")
        self.headers = {"Authorization": "Bearer %s" % self.token, "Content-Type": "application/json"}

    def test_unauthenticated(self):
        resp = self.client.post("/mcp/regression/flux/quick-fix", json={"jira_key": "ENG-1"})
        self.assertEqual(resp.status_code, 401)

    def test_missing_flux_credentials(self):
        with patch.object(self.tf, "get_user_key", return_value=None):
            resp = self.client.post(
                "/mcp/regression/flux/quick-fix",
                json={"jira_key": "ENG-1", "target_branch": "master"},
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 403)
        body = resp.get_json()
        self.assertIn("Flux username and password required", body.get("error"))

    def test_requires_jira_and_branch(self):
        def fake_key(username, name):
            return {"flux_username": "alice", "flux_password": "pw"}.get(name)
        
        with patch.object(self.tf, "get_user_key", side_effect=fake_key):
            resp = self.client.post(
                "/mcp/regression/flux/quick-fix",
                json={"target_branch": "master"},
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 400)

    def test_missing_user_keys(self):
        def fake_key(username, name):
            # Return Flux creds but not cursor_api_key or gerrit_http_password
            return {"flux_username": "alice", "flux_password": "pw"}.get(name)
        
        with patch.object(self.tf, "get_user_key", side_effect=fake_key):
            resp = self.client.post(
                "/mcp/regression/flux/quick-fix",
                json={"jira_key": "ENG-1", "target_branch": "master"},
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 403)
        body = resp.get_json()
        self.assertTrue(body.get("require_key_setup"))
        self.assertEqual(body.get("missing_key"), "cursor_api_key")

    def test_quick_fix_resume_ticket_proxy(self):
        mock_client = MagicMock()
        mock_client.start_quick_fix.return_value = {"record_id": 21, "status": "queued"}
        mock_client.get_ticket.return_value = {"id": 21, "status": "awaiting_review"}
        mock_client.resume_ticket.return_value = {"record_id": 21, "status": "fixing"}

        def fake_key(username, name):
            return {
                "flux_username": "alice",
                "flux_password": "pw",
                "cursor_api_key": "crsr_x",
                "gerrit_http_password": "gerrit-pass"
            }.get(name)

        with patch.object(self.tf, "get_user_key", side_effect=fake_key), \
             patch.object(self.tf, "get_flux_client", return_value=mock_client):
            queued = self.client.post(
                "/mcp/regression/flux/quick-fix",
                json={
                    "jira_key": "ENG-968649",
                    "target_branch": "ganges-7.5-stable",
                    "log_url": None,
                },
                headers=self.headers,
            )
            ticket = self.client.get("/mcp/regression/flux/tickets/21", headers=self.headers)
            resumed = self.client.post("/mcp/regression/flux/tickets/21/resume", headers=self.headers)

        self.assertEqual(queued.status_code, 200)
        self.assertEqual(queued.get_json()["record_id"], 21)
        mock_client.start_quick_fix.assert_called_once()
        kwargs = mock_client.start_quick_fix.call_args.kwargs
        self.assertEqual(kwargs["jira_key"], "ENG-968649")
        self.assertEqual(kwargs["target_branch"], "ganges-7.5-stable")
        self.assertIsNone(kwargs["log_url"])
        self.assertEqual(kwargs["cursor_api_key"], "crsr_x")
        self.assertEqual(kwargs["gerrit_http_password"], "gerrit-pass")
        self.assertEqual(ticket.status_code, 200)
        self.assertEqual(ticket.get_json()["status"], "awaiting_review")
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.get_json()["status"], "fixing")

    def test_maps_short_branch_to_nutest_git_branch(self):
        mock_client = MagicMock()
        mock_client.start_quick_fix.return_value = {"record_id": 23, "status": "queued"}

        def fake_key(username, name):
            return {
                "flux_username": "alice",
                "flux_password": "pw",
                "cursor_api_key": "crsr_x",
                "gerrit_http_password": "gerrit-pass",
            }.get(name)

        with patch.object(self.tf, "get_user_key", side_effect=fake_key), \
             patch.object(self.tf, "get_flux_client", return_value=mock_client):
            resp = self.client.post(
                "/mcp/regression/flux/quick-fix",
                json={"jira_key": "ENG-968649", "target_branch": "7.5"},
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            mock_client.start_quick_fix.call_args.kwargs["target_branch"],
            "ganges-7.5-stable",
        )

    def test_nutest_branch_from_jita_agave_task(self):
        self.assertEqual(
            self.tf.nutest_branch_from_agave_task({
                "nutest-py3-tests_branch": "ganges-7.5-stable",
            }),
            "ganges-7.5-stable",
        )
        self.assertEqual(
            self.tf.nutest_branch_from_agave_task({
                "test_framework_metadata": {"framework": {"branch": "ganges-7.5-stable"}},
            }),
            "ganges-7.5-stable",
        )

    def test_flux_nutest_branch_endpoint(self):
        with patch.object(self.tf, "fetch_agave_task", return_value={
            "nutest-py3-tests_branch": "ganges-7.5-stable",
        }):
            resp = self.client.get(
                "/mcp/regression/flux/nutest-branch?task_id=6aa14a9f8e79cef74002229a",
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["nutest_branch"], "ganges-7.5-stable")
        self.assertEqual(body["nutest-py3-tests_branch"], "ganges-7.5-stable")


if __name__ == "__main__":
    unittest.main()
