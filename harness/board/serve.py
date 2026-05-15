import json
import os
import threading
import http.server
import urllib.parse
from pathlib import Path
from harness.board.core import JobBoard, Task, Level, State

PORT = int(os.environ.get("MONSTER_BOARD_PORT", "8080"))
BOARD_DIR = Path(os.environ.get("MONSTER_BOARD_DIR", str(Path.home() / ".monster" / "board")))

ICONS = {"backlog": "○", "ready": "◉", "in_progress": "◎", "blocked": "⊘", "done": "●", "archived": "·"}
LEVEL_COLORS = {"epic": "#6c5ce7", "task": "#00b894", "unit": "#fdcb6e"}

KANBAN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>monster board</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background:#1a1a2e; color:#eee; padding:20px; }
h1 { font-size:1.2rem; margin-bottom:16px; color:#a0a0c0; letter-spacing:0.5px; }
h1 span { color:#6c5ce7; }
.board { display:flex; gap:12px; overflow-x:auto; padding-bottom:20px; min-height:70vh; }
.col { background:#16213e; border-radius:8px; min-width:220px; max-width:260px; flex:1; padding:8px; }
.col-header { font-size:0.75rem; font-weight:600; text-transform:uppercase; letter-spacing:1px; padding:8px 10px; color:#8888aa; border-bottom:1px solid #2a2a4a; margin-bottom:8px; display:flex; justify-content:space-between; }
.col-header .count { color:#555; font-size:0.7rem; }
.card { background:#1e2a4a; border-radius:6px; padding:10px; margin-bottom:6px; cursor:grab; border-left:3px solid #555; transition:background 0.15s, box-shadow 0.15s; position:relative; }
.card:hover { background:#25325a; box-shadow:0 2px 8px rgba(0,0,0,0.3); }
.card.dragging { opacity:0.4; }
.card .level { font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:4px; }
.card .title { font-size:0.8rem; line-height:1.3; }
.card .meta { font-size:0.65rem; color:#666; margin-top:4px; }
.card .del { position:absolute; top:4px; right:6px; cursor:pointer; color:#555; font-size:0.8rem; line-height:1; padding:2px 4px; border-radius:3px; }
.card .del:hover { color:#e74c3c; background:rgba(231,76,60,0.15); }
.col.drag-over { background:#1c2a50; outline:2px dashed #6c5ce7; }
.modal { display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.6); z-index:100; justify-content:center; align-items:center; }
.modal.open { display:flex; }
.modal-content { background:#16213e; border-radius:10px; padding:24px; max-width:500px; width:90%; max-height:80vh; overflow-y:auto; }
.modal-content h2 { font-size:1rem; margin-bottom:12px; }
.modal-content .field { margin-bottom:10px; }
.modal-content label { display:block; font-size:0.7rem; color:#8888aa; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:4px; }
.modal-content input, .modal-content select, .modal-content textarea { width:100%; padding:8px; background:#1a1a2e; border:1px solid #2a2a4a; border-radius:4px; color:#eee; font-size:0.85rem; }
.modal-content textarea { min-height:60px; resize:vertical; font-family:inherit; }
.modal-content .btn-row { display:flex; gap:8px; justify-content:flex-end; margin-top:12px; }
.btn { padding:8px 16px; border:none; border-radius:4px; cursor:pointer; font-size:0.8rem; }
.btn-primary { background:#6c5ce7; color:#fff; }
.btn-primary:hover { background:#7c6cf7; }
.btn-secondary { background:#2a2a4a; color:#aaa; }
.btn-secondary:hover { background:#3a3a5a; }
.btn-danger { background:#e74c3c; color:#fff; }
.btn-danger:hover { background:#ff5e4a; }
.toolbar { display:flex; gap:8px; margin-bottom:16px; align-items:center; }
.toolbar .status { font-size:0.75rem; color:#555; margin-left:auto; }
.prompt { font-size:0.8rem; color:#aaa; background:#1a1a2e; padding:8px; border-radius:4px; margin:8px 0; white-space:pre-wrap; }
.result { font-size:0.8rem; color:#00b894; background:#1a2a1e; padding:8px; border-radius:4px; margin:8px 0; white-space:pre-wrap; }
.result-preview { font-size:0.7rem; color:#00b894; background:#1a2a1e; padding:4px 6px; border-radius:3px; margin-top:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:100%; }
.id { font-size:0.65rem; color:#555; font-family:monospace; }
</style>
</head>
<body>
<h1>monster <span>board</span></h1>
<div class="toolbar">
  <button class="btn btn-primary" onclick="showNewTask()">+ new task</button>
  <span class="status" id="status">—</span>
</div>
<div class="board" id="board"></div>

<div class="modal" id="modal">
  <div class="modal-content" id="modalContent"></div>
</div>

<script>
const STATES = ["backlog", "ready", "in_progress", "blocked", "done"];
const LEVELS = ["epic", "task", "unit"];
const ICONS = {"backlog":"○","ready":"◉","in_progress":"◎","blocked":"⊘","done":"●","archived":"·"};
const LEVEL_COLORS = {"epic":"#6c5ce7","task":"#00b894","unit":"#fdcb6e"};

let tasks = [];

async function api(method, path, body) {
  const opts = { method, headers: {"Content-Type":"application/json"} };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch("/api" + path, opts);
  if (!r.ok) throw await r.text();
  return r.headers.get("content-type")?.includes("json") ? r.json() : null;
}

async function load() {
  tasks = await api("GET", "/tasks");
  render();
  document.getElementById("status").textContent = new Date().toLocaleTimeString();
}

function render() {
  const board = document.getElementById("board");
  board.innerHTML = "";
  for (const s of STATES) {
    const col = document.createElement("div");
    col.className = "col";
    col.dataset.state = s;
    col.addEventListener("dragover", e => { e.preventDefault(); col.classList.add("drag-over"); });
    col.addEventListener("dragleave", () => col.classList.remove("drag-over"));
    col.addEventListener("drop", e => {
      e.preventDefault();
      col.classList.remove("drag-over");
      const id = e.dataTransfer.getData("text/plain");
      moveTask(id, s);
    });
    const items = tasks.filter(t => t.state === s).sort((a,b) => a.created < b.created ? -1 : 1);
    col.innerHTML = `<div class="col-header">${ICONS[s]} ${s.replace("_"," ")} <span class="count">${items.length}</span></div>`;
    for (const t of items) {
      const card = document.createElement("div");
      card.className = "card";
      card.draggable = true;
      card.style.borderLeftColor = LEVEL_COLORS[t.level] || "#555";
      card.dataset.id = t.id;
      card.addEventListener("dragstart", e => { e.dataTransfer.setData("text/plain", t.id); card.classList.add("dragging"); });
      card.addEventListener("dragend", () => card.classList.remove("dragging"));
      card.addEventListener("click", () => showDetail(t.id));
      card.innerHTML = `<div class="level" style="color:${LEVEL_COLORS[t.level]}">${t.level}</div><div class="title">${esc(t.title)}</div>${t.result && t.state==="done" ? `<div class="result-preview">${esc(t.result.slice(0,80))}${t.result.length>80?"…":""}</div>` : ""}<div class="meta">${t.caste || "—"} · ${t.id.slice(0,8)}</div><span class="del" onclick="event.stopPropagation();deleteTask('${t.id}')">×</span>`;
      col.appendChild(card);
    }
    board.appendChild(col);
  }
}

async function moveTask(id, state) {
  await api("PATCH", "/tasks/" + id, { state });
  await load();
}

async function showDetail(id) {
  const t = tasks.find(x => x.id === id);
  if (!t) return;
  const m = document.getElementById("modalContent");
  m.innerHTML = `
    <h2>${esc(t.title)}</h2>
    <div class="field"><label>id</label><div class="id">${t.id}</div></div>
    <div class="field"><label>level</label><div style="color:${LEVEL_COLORS[t.level]}">${t.level.toUpperCase()}</div></div>
    <div class="field"><label>state</label><div>${ICONS[t.state]} ${t.state}</div></div>
    <div class="field"><label>caste</label><div>${t.caste || "—"}</div></div>
    ${t.prompt ? `<div class="field"><label>prompt</label><div class="prompt">${esc(t.prompt)}</div></div>` : ""}
    ${t.result ? `<div class="field"><label>result</label><div class="result">${esc(t.result)}</div></div>` : ""}
    <div class="field"><label>created</label><div style="font-size:0.75rem;color:#888">${t.created}</div></div>
    <div class="field"><label>updated</label><div style="font-size:0.75rem;color:#888">${t.updated}</div></div>
    <div class="btn-row">
      <button class="btn btn-danger" onclick="deleteTask('${t.id}')">delete</button>
      <button class="btn btn-secondary" onclick="closeModal()">close</button>
    </div>`;
  document.getElementById("modal").classList.add("open");
}

function showNewTask() {
  const m = document.getElementById("modalContent");
  m.innerHTML = `
    <h2>new task</h2>
    <div class="field"><label>level</label><select id="new-level">${LEVELS.map(l => `<option value="${l}">${l}</option>`).join("")}</select></div>
    <div class="field"><label>title</label><input id="new-title" placeholder="task title" autofocus></div>
    <div class="field"><label>prompt</label><textarea id="new-prompt" placeholder="optional prompt"></textarea></div>
    <div class="btn-row">
      <button class="btn btn-secondary" onclick="closeModal()">cancel</button>
      <button class="btn btn-primary" onclick="postTask()">post</button>
    </div>`;
  document.getElementById("modal").classList.add("open");
  setTimeout(() => document.getElementById("new-title")?.focus(), 100);
}

async function postTask() {
  const title = document.getElementById("new-title").value.trim();
  if (!title) return;
  const level = document.getElementById("new-level").value;
  const prompt = document.getElementById("new-prompt").value.trim() || title;
  await api("POST", "/tasks", { level, title, prompt });
  closeModal();
  await load();
}

async function deleteTask(id) {
  if (!confirm("delete this task?")) return;
  await api("DELETE", "/tasks/" + id);
  closeModal();
  await load();
}
function closeModal() { document.getElementById("modal").classList.remove("open"); }
function esc(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

load();
setInterval(load, 5000);
</script>
</body>
</html>"""


class BoardHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, data, status=200, ctype="application/json"):
        if isinstance(data, str):
            data = data.encode()
        elif not isinstance(data, bytes):
            data = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _path_parts(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = urllib.parse.parse_qs(parsed.query)
        return path, qs

    def do_GET(self):
        path, qs = self._path_parts()
        if path == "/":
            self._send(KANBAN_HTML, ctype="text/html; charset=utf-8")
        elif path == "/api/tasks":
            board = JobBoard()
            level = qs.get("level", [None])[0]
            state = qs.get("state", [None])[0]
            level_enum = Level(level) if level and level in [e.value for e in Level] else None
            state_enum = State(state) if state and state in [e.value for e in State] else None
            items = [t.to_dict() for t in board.list(level=level_enum, state=state_enum)]
            self._send(items)
        elif path.startswith("/api/tasks/"):
            task_id = path.split("/api/tasks/")[1]
            board = JobBoard()
            t = board.get(task_id)
            if t is None:
                self._send({"error": "not found"}, 404)
            else:
                self._send(t.to_dict())
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        path, _ = self._path_parts()
        if path == "/api/tasks":
            body = self._read_body()
            level = body.get("level", "task")
            title = body.get("title", "untitled")
            prompt = body.get("prompt", title)
            board = JobBoard()
            t = Task(level=Level(level), title=title, prompt=prompt)
            board.create(t)
            self._send(t.to_dict(), 201)
        elif path == "/shutdown":
            self._send({"status": "stopping"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._send({"error": "not found"}, 404)

    def do_PATCH(self):
        path, _ = self._path_parts()
        if path.startswith("/api/tasks/"):
            task_id = path.split("/api/tasks/")[1]
            body = self._read_body()
            board = JobBoard()
            t = board.get(task_id)
            if t is None:
                self._send({"error": "not found"}, 404)
                return
            if "state" in body:
                new_state = State(body["state"])
                if t.level == Level.EPIC and new_state == State.DONE:
                    t.transition(new_state)
                else:
                    t.transition(new_state)
                board.update(t)
            if "caste" in body:
                t.caste = body["caste"]
                board.update(t)
            if "result" in body:
                t.result = body["result"]
                board.update(t)
            self._send(t.to_dict())
        else:
            self._send({"error": "not found"}, 404)

    def do_DELETE(self):
        path, _ = self._path_parts()
        if path.startswith("/api/tasks/"):
            task_id = path.split("/api/tasks/")[1]
            board = JobBoard()
            if board.delete(task_id):
                self._send({"status": "removed"})
            else:
                self._send({"error": "not found"}, 404)
        else:
            self._send({"error": "not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def serve(port: int = PORT):
    addr = ("0.0.0.0", port)
    server = http.server.HTTPServer(addr, BoardHandler)
    print(f"γ|board|serve|http://localhost:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("γ|board|stop", flush=True)
        server.server_close()
