import http.client
import json
import os
import selectors
import signal
import subprocess
import sys
import threading
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from ellie.ui import make_server, snapshot
from tests.support import IsolatedTest


class UITests(IsolatedTest):
    def test_conversation_filter_does_not_return_unselected_text_or_later_versions(self):
        self.memory()
        a = self.store.add_item(self.project, "work", "Q", "Alpha question", {"status": "open"}, session="chat-a")
        self.store.add_item(self.project, "work", "N", "Beta item", {}, body="Excluded beta body", session="chat-b")
        self.store.resolve(self.project, a, "Excluded beta answer", session="chat-b")
        self.store.update_memory(self.project, "work", lambda m: m.set_section("Current state", "Excluded global state"))
        self.server()
        data = self.get("/api/snapshot", project=self.project, conversation="chat-a")
        payload = json.dumps(data["project"]["memories"])
        self.assertIn("Alpha question", payload)
        for text in ("Excluded beta body", "Excluded beta answer", "Excluded global state"):
            self.assertNotIn(text, payload)
        self.assertEqual(self.get("/api/search", project=self.project, q="beta", conversation="chat-a")["items"], [])
        self.assertIn("capture_health", data["project"])
        self.assertEqual({record["id"] for record in data["project"]["conversations"]}, {"chat-a", "chat-b"})
        combined = self.get("/api/snapshot", project=self.project, conversation=["chat-a", "chat-b"])
        self.assertIn("Excluded beta body", json.dumps(combined["project"]["memories"]))
        self.assertEqual(self.get("/api/snapshot", project=self.project, scope="selected")["project"]["memories"], [])

    def server(self):
        server = make_server(self.store, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def close():
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.addCleanup(close)
        self.url = f"http://127.0.0.1:{server.server_port}"
        return server

    def get(self, path, **params):
        with urlopen(self.url + path + ("?" + urlencode(params, doseq=True) if params else ""), timeout=10) as response:
            return json.loads(response.read())

    def test_empty_snapshot_does_not_create_files(self):
        before = list(self.store.root.rglob("*"))
        data = snapshot(self.store)
        self.assertEqual(data["projects"], [])
        self.assertIsNone(data["project"])
        self.assertEqual(list(self.store.root.rglob("*")), before)

    def test_snapshot_reads_saved_context_archives_and_capture_records(self):
        self.memory()
        self.store.update_memory(self.project, "work", lambda m: m.set_section("Current state", "Ready for review"))
        id = self.store.add_item(self.project, "work", "F", "Cookie limitation", {"detail": "Cross-site blocked", "scope": "workstream"})
        self.store.create_memory(self.project, "old")
        self.store.move_memory(self.project, "old", True)
        self.store.write_sessions(self.project, {"session-1": {"agent": "codex", "capture": "done", "memories": ["work"], "archive": "private-transcript", "cwd": "private-path"}})
        self.store.write_pending("run-1", {"project": self.project, "capture": "failed", "error": "Timeout", "agent": "claude", "prompt": "not exposed"})
        before = {m.name: m.to_bytes() for m in self.store.iter_memories(self.project)}
        self.server()
        data = self.get("/api/snapshot", project=self.project)
        self.assertEqual(data["projects"][0]["workstreams"], 1)
        self.assertEqual(data["projects"][0]["items"], 1)
        memories = {m["name"]: m for m in data["project"]["memories"]}
        self.assertIn("Ready for review", memories["work"]["sections"]["Current state"])
        self.assertEqual(memories["work"]["items"][0]["id"], id)
        self.assertTrue(memories["old"]["archived"])
        session = data["project"]["sessions"][0]
        self.assertEqual(session["id"], "session-1")
        self.assertNotIn("archive", session)
        self.assertNotIn("cwd", session)
        self.assertEqual(data["project"]["pending"][0]["error"], "Timeout")
        self.assertNotIn("prompt", data["project"]["pending"][0])
        self.assertEqual(before, {m.name: m.to_bytes() for m in self.store.iter_memories(self.project)})

    def test_project_switching_and_ranked_search_preserve_memory(self):
        self.memory()
        old = self.store.add_item(self.project, "work", "N", "Refresh attempt", {"date": "2020-01-01"})
        failed = self.store.add_item(self.project, "work", "R", "Refresh attempt", {"outcome": "failed", "what": "Refresh"})
        self.store.create_memory("local/other", "other")
        self.store.add_item("local/other", "other", "N", "Refresh unrelated", {})
        self.store.move_memory(self.project, "work", True)
        before = {m.name: m.to_bytes() for m in self.store.iter_memories(self.project)}
        self.server()
        data = self.get("/api/search", project=self.project, q="refresh")
        self.assertEqual([hit["id"] for hit in data["items"]], [failed, old])
        switched = self.get("/api/snapshot", project="local/other")
        self.assertEqual(switched["project"]["id"], "local/other")
        self.assertEqual(self.get("/api/search", project=self.project, q="")['items'], [])
        self.assertEqual(before, {m.name: m.to_bytes() for m in self.store.iter_memories(self.project)})

    def test_assets_and_untrusted_memory_are_data(self):
        self.memory()
        title = '</script><img src=x onerror="alert(1)">'
        self.store.add_item(self.project, "work", "N", title, {})
        self.server()
        for path, content_type in (("/", "text/html"), ("/assets/app.js", "text/javascript"), ("/assets/style.css", "text/css")):
            with urlopen(self.url + path, timeout=5) as response:
                text = response.read().decode()
                self.assertIn(content_type, response.headers["Content-Type"])
                self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertNotIn(title, text)
                if path.endswith("app.js"):
                    self.assertNotIn("innerHTML", text)
        self.assertEqual(self.get("/api/snapshot")["project"]["memories"][1]["items"][0]["title"], title)

    def test_loopback_origin_and_method_boundaries(self):
        server = self.server()
        for headers in ({"Host": "evil.example"}, {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", "/api/snapshot", headers=headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            connection.close()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request("POST", "/api/snapshot", body=b"{}")
        response = connection.getresponse()
        self.assertEqual(response.status, 405)
        response.read()
        connection.close()
        for path in ("/assets/../../store", "/api/snapshot?project=../../other", "/api/search?project=missing&q=test"):
            with self.assertRaises(HTTPError) as error:
                urlopen(self.url + path, timeout=5)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()

    def test_cli_serves_in_real_process_and_stops_cleanly(self):
        self.memory()
        checkout = self.root / "checkout"
        checkout.mkdir()
        (checkout / "unchanged.txt").write_text("keep")
        process = subprocess.Popen([sys.executable, "-m", "ellie", "ui", "--port", "0", "--no-open"],
                                   cwd=checkout, env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def close():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
        self.addCleanup(close)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(10), "UI never printed its URL")
        line = process.stdout.readline().strip()
        self.assertTrue(line.startswith("Ellie dashboard: http://127.0.0.1:"), line)
        self.assertIn("Read-only", process.stdout.readline())
        with urlopen(line.split(": ", 1)[1] + "/api/snapshot", timeout=5) as response:
            self.assertEqual(json.load(response)["project"]["id"], self.project)
        process.send_signal(signal.SIGINT)
        out, err = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, err)
        self.assertEqual([p.name for p in checkout.iterdir()], ["unchanged.txt"])
        self.assertEqual((checkout / "unchanged.txt").read_text(), "keep")

    def test_invalid_port_has_clear_cli_error(self):
        result = subprocess.run([sys.executable, "-m", "ellie", "ui", "--port", "65536", "--no-open"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertIn("port must be between", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
