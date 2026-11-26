"""Real Codex against a loopback-only canned responder; no login or model."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

from ellie.agents import adapter
from ellie.extract import SCHEMA, clean_environment
from tests.fake_agents import empty_extraction
from tests.support import IsolatedTest


class NativeCodexTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.executable = shutil.which("codex")
        if not self.executable:
            self.skipTest("Codex is not installed")
        self.value = empty_extraction("work", worthwhile=False)
        self.answer = json.dumps(self.value)
        self.requests = []
        test = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"data":[]}')

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                test.requests.append({"body": body, "has_auth": bool(self.headers.get("Authorization"))})
                message_id = "msg_qa_" + str(len(test.requests))
                item = {"id": message_id, "type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": test.answer, "annotations": []}]}
                response = {"id": "resp_qa_" + str(len(test.requests)), "object": "response", "created_at": int(time.time()), "status": "completed",
                            "model": body.get("model"), "output": [item],
                            "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20}}
                events = [
                    {"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
                    {"type": "response.output_item.added", "output_index": 0, "item": {**item, "status": "in_progress", "content": []}},
                    {"type": "response.content_part.added", "item_id": message_id, "output_index": 0, "content_index": 0,
                     "part": {"type": "output_text", "text": "", "annotations": []}},
                    {"type": "response.output_text.delta", "item_id": message_id, "output_index": 0, "content_index": 0, "delta": test.answer},
                    {"type": "response.output_text.done", "item_id": message_id, "output_index": 0, "content_index": 0, "text": test.answer},
                    {"type": "response.output_item.done", "output_index": 0, "item": item},
                    {"type": "response.completed", "response": response},
                ]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                for event in events:
                    self.wfile.write(("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode())
                self.wfile.flush()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        def close():
            self.server.shutdown()
            self.server.server_close()
            thread.join(timeout=5)
        self.addCleanup(close)

    def command(self, directory, session=None):
        directory.mkdir()
        schema, output = directory / "schema.json", directory / "out.json"
        schema.write_text(json.dumps(SCHEMA))
        command = adapter("codex").command(self.executable, session, directory, schema, output, ["sample"])
        provider = ('model_providers.qa={name="QA",base_url="http://127.0.0.1:' + str(self.server.server_port)
                    + '/v1",wire_api="responses",requires_openai_auth=false,supports_websockets=false,request_max_retries=0,stream_max_retries=0}')
        command[2:2] = ["-c", 'model_provider="qa"', "-c", 'model="gpt-5.1-codex"', "-c", provider]
        return command, output

    def execute(self, command, directory):
        result = subprocess.run(command, input="Return the empty extraction JSON.", cwd=directory,
                                env=clean_environment(), capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ephemeral_extraction_runs_outside_git_with_no_auth_or_history(self):
        directory = self.root / "extraction"
        command, output = self.command(directory)
        self.execute(command, directory)
        self.assertEqual(json.loads(output.read_text()), self.value)
        self.assertEqual(len(self.requests), 1)
        self.assertFalse(self.requests[0]["has_auth"])
        self.assertEqual(self.requests[0]["body"]["text"]["format"]["schema"], SCHEMA)
        self.assertEqual(list(Path(os.environ["CODEX_HOME"]).glob("sessions/**/*.jsonl")), [])

    def test_ephemeral_native_fork_preserves_the_original_transcript(self):
        seed = self.root / "seed"
        command, _ = self.command(seed)
        command.remove("--ephemeral")
        self.execute(command, seed)
        paths = list(Path(os.environ["CODEX_HOME"]).glob("sessions/**/*.jsonl"))
        self.assertEqual(len(paths), 1)
        original = {path: path.read_bytes() for path in paths}
        session = adapter("codex").read(paths[0])
        self.assertEqual(session.user_messages, 1)
        fork = self.root / "fork"
        command, output = self.command(fork, session.id)
        self.execute(command, fork)
        self.assertEqual(json.loads(output.read_text()), self.value)
        self.assertEqual({path: path.read_bytes() for path in Path(os.environ["CODEX_HOME"]).glob("sessions/**/*.jsonl")}, original)
        self.assertTrue(all(not request["has_auth"] for request in self.requests))

    def test_persisted_branch_can_be_forked_by_its_physical_history_id(self):
        seed = self.root / "seed"
        command, _ = self.command(seed)
        command.remove("--ephemeral")
        self.execute(command, seed)
        root = Path(os.environ["CODEX_HOME"])
        parent_path = next(root.glob("sessions/**/*.jsonl"))
        parent = adapter("codex").read(parent_path)
        branch = self.root / "branch"
        command, _ = self.command(branch, parent.history_id)
        command.remove("--ephemeral")
        self.execute(command, branch)
        child_path = next(path for path in root.glob("sessions/**/*.jsonl") if path != parent_path)
        child = adapter("codex").read(child_path)
        self.assertNotEqual(child.history_id, parent.history_id)
        originals = {path: path.read_bytes() for path in root.glob("sessions/**/*.jsonl")}
        extraction = self.root / "branch-extraction"
        command, output = self.command(extraction, child.history_id)
        self.execute(command, extraction)
        self.assertEqual(json.loads(output.read_text()), self.value)
        self.assertEqual({path: path.read_bytes() for path in root.glob("sessions/**/*.jsonl")}, originals)
        self.assertTrue(all(not request["has_auth"] for request in self.requests))
