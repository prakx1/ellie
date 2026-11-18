import json
import os
import subprocess
import sys

from tests.support import IsolatedTest


class MCPTests(IsolatedTest):
    def exchange(self, messages, **overrides):
        env = os.environ.copy()
        env.pop("ELLIE_AGENT", None)
        env.pop("ELLIE_RUN_ID", None)
        env.update(overrides)
        process = subprocess.run([sys.executable, "-m", "ellie.mcp_server"],
                                 input="\n".join(json.dumps(m) if not isinstance(m, str) else m for m in messages) + "\n",
                                 cwd=self.root, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        return [json.loads(line) for line in process.stdout.splitlines()]

    def request(self, id, method, params=None):
        return {"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}

    def call(self, request_id, tool_name, **arguments):
        return self.request(request_id, "tools/call", {"name": tool_name, "arguments": {"project": self.project, **arguments}})

    def test_real_subprocess_all_tools_and_retry(self):
        messages = [
            self.request(1, "initialize", {"protocolVersion": "2025-06-18", "clientInfo": {"name": "codex-test"}}),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            self.request(2, "tools/list"),
            self.call(3, "status"),
            self.call(4, "create", name="auth", description="Auth work", goal="Migrate", done_when="Tests pass"),
            self.call(5, "set_goal", memory="auth", goal="PKCE", done_when="Old login removed"),
            self.call(6, "decide", memory="auth", title="Use authlib", options=["authlib", "custom"], chosen="authlib", tradeoff="dependency", why="Less security code"),
            self.call(7, "decide", memory="auth", title="Use authlib", options=["authlib", "custom"], chosen="authlib", tradeoff="dependency", why="Less security code"),
            self.call(8, "result", memory="auth", title="Iframe refresh", outcome="failed", what="Silent refresh", evidence="Safari ITP blocks it"),
            self.call(9, "finding", memory="auth", title="Gateway header", detail="Use X-Real-IP", scope="project"),
            self.call(10, "question", memory="auth", text="Can internal callers bypass?"),
            self.call(11, "resolve", id="Q1", answer="They cannot"),
            self.call(12, "log", memory="auth", entry="Tests green", kind="progress"),
            self.call(13, "update", memory="auth", section="Current state", content="PKCE works"),
            self.call(14, "handoff", memory="auth", current_state="Refresh works", next_steps="Migrate clients", session_summary="Auth endpoint done"),
            self.call(15, "load", memories=["auth"]),
            self.call(16, "recall", query="iframe", types=["R"]),
            self.call(17, "get", ids=["D1", self.project + ":F1"]),
            self.request(18, "ping"), self.request(19, "resources/list"), self.request(20, "prompts/list"),
        ]
        responses = self.exchange(messages)
        self.assertEqual(len(responses), 20)
        by_id = {response["id"]: response for response in responses}
        self.assertEqual(by_id[1]["result"]["protocolVersion"], "2025-06-18")
        tools = by_id[2]["result"]["tools"]
        self.assertEqual(len(tools), 18)
        self.assertTrue(all(tool["description"] for tool in tools))
        for response in responses:
            self.assertNotIn("error", response)
            self.assertFalse(response["result"].get("isError", False), response)
        self.assertEqual(by_id[6]["result"]["structuredContent"], {"id": "D1"})
        self.assertEqual(by_id[7]["result"]["structuredContent"], {"id": "D1"})
        loaded = by_id[15]["result"]["structuredContent"]["briefing"]
        self.assertIn("Refresh works", loaded)
        self.assertIn("Iframe refresh", loaded)
        self.assertNotIn("### Q1", loaded)
        self.assertEqual(by_id[16]["result"]["structuredContent"]["items"][0]["id"], "R1")
        self.assertEqual(self.store.get_item(self.project, "D1")[1].fields["source"], "codex · live")
        self.assertEqual(self.store.get_item(self.project, "F1")[0], "project")

    def test_errors_do_not_crash_or_corrupt_memory(self):
        self.memory()
        messages = ["{broken", [], self.request(1, "unknown"),
                    self.call(2, "update", memory="work", section="Log", content="erase"),
                    self.call(3, "question", memory="missing", text="No"),
                    self.call(4, "question", memory="work"),
                    self.call(5, "recall", query="hello", limit=True),
                    self.call(6, "no-such-tool"),
                    self.call(7, "create", name="../escape", description="no"),
                    self.request(8, "ping")]
        responses = self.exchange(messages)
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertEqual(responses[1]["error"]["code"], -32600)
        self.assertEqual(responses[2]["error"]["code"], -32601)
        self.assertTrue(all(r["result"]["isError"] for r in responses[3:-1]))
        self.assertEqual(responses[-1]["result"], {})
        self.assertEqual(self.store.read_memory(self.project, "work").items, [])

    def test_project_precedence_and_agent_override(self):
        responses = self.exchange([
            self.request(1, "initialize", {"clientInfo": {"name": "claude-code"}}),
            self.call(2, "create", cwd="/not/a/repo", name="auth", description="Work"),
            self.call(3, "question", memory="auth", text="Why?")], ELLIE_AGENT="codex")
        self.assertFalse(responses[-1]["result"]["isError"])
        self.assertEqual(self.store.get_item(self.project, "Q1")[1].fields["source"], "codex · live")

    def test_handoff_records_known_session_and_pending_marker(self):
        self.memory()
        self.store.write_pending("fixture-run", {"project": self.project, "session_id": "fixture-session"})
        responses = self.exchange([self.call(1, "handoff", memory="work", current_state="Done", next_steps="Ship", session_summary="Ready")], ELLIE_RUN_ID="fixture-run")
        self.assertFalse(responses[0]["result"]["isError"])
        self.assertIn("session fixture-session", self.store.read_memory(self.project, "work").get_section("Log"))
        self.assertIn("work", self.store.read_pending("fixture-run")["live_handoffs"])

    def test_conversation_scope_survives_interleaved_requests_in_one_process(self):
        self.memory("auth")
        self.memory("billing")
        responses = self.exchange([
            self.call(1, "bind", session_id="chat-a", memories=["auth"], conversations=[]),
            self.call(2, "bind", session_id="chat-b", memories=["billing"], conversations=[]),
            self.call(3, "question", session_id="chat-a", memory="auth", text="Alpha question"),
            self.call(4, "question", session_id="chat-b", memory="billing", text="Beta question"),
            self.call(5, "recall", session_id="chat-a", query="question"),
            self.call(6, "get", session_id="chat-a", ids=["Q2"]),
            self.call(7, "timeline", session_id="chat-b", anchor="Q2"),
            self.call(8, "conversations"),
            self.call(9, "get", ids=["Q2"]),
        ])
        self.assertEqual([item["id"] for item in responses[4]["result"]["structuredContent"]["items"]], ["Q1"])
        self.assertTrue(responses[5]["result"]["isError"])
        self.assertEqual([item["id"] for item in responses[6]["result"]["structuredContent"]["items"]], ["Q2"])
        self.assertEqual(len(responses[7]["result"]["structuredContent"]["conversations"]), 2)
        self.assertTrue(responses[8]["result"]["isError"])
        self.assertIn("session_id", responses[8]["result"]["content"][0]["text"])
