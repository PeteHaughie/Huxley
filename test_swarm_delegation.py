#!/usr/bin/env python3
"""End-to-end swarm delegation test: Leader (8083) + βγ Worker (8084)."""

import os, sys, json, socket, time, threading, http.server, subprocess, signal
from pathlib import Path

WORKER_PORT = 8084
LEADER_PORT = 8083
MULTICAST_PORT = 43210
MULTICAST_GROUP = "239.255.43.21"
PID_PATH = Path.home() / ".huxley" / "huxleyd.pid"
LOG_PATH = Path.home() / ".huxley" / "huxleyd.log"

def _build_announce(hostname, port, castes="βγ", load=0.0):
    return json.dumps({"type":"huxley_announce","hostname":hostname,"port":port,"castes":castes,"load":load,"version":"0.1.0"}).encode()

def _lan_ips():
    import subprocess as sp
    ips = []
    try:
        r = sp.run(["ifconfig","-l"], capture_output=True, text=True, timeout=3)
        for name in r.stdout.strip().split():
            r2 = sp.run(["ifconfig",name], capture_output=True, text=True, timeout=3)
            for line in r2.stdout.splitlines():
                line = line.strip()
                if line.startswith("inet ") and "127.0.0.1" not in line:
                    ip = line.split()[1]
                    if ip not in ips: ips.append(ip)
    except: pass
    return ips

def send_announce(hostname, port, castes="βγ"):
    data = _build_announce(hostname, port, castes=castes)
    for ip in _lan_ips():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
            s.sendto(data, (MULTICAST_GROUP, MULTICAST_PORT))
        except OSError: pass
        s.close()
        s2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s2.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s2.sendto(data, ("255.255.255.255", MULTICAST_PORT))
        s2.close()
    print(f"  [announce] {hostname}:{port} castes={castes}", flush=True)

def announce_loop(hostname, port, castes="βγ", interval=8):
    while True:
        send_announce(hostname, port, castes)
        time.sleep(interval)

class WorkerHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass
    def _send(self, data, status=200):
        if isinstance(data, str): data = data.encode()
        elif not isinstance(data, bytes): data = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def _read_body(self):
        length = int(self.headers.get("Content-Length",0))
        return json.loads(self.rfile.read(length)) if length else {}
    def do_GET(self):
        p = self.path.rstrip("/")
        if p == "/v1/load":       self._send({"load":0})
        elif p == "/health":      self._send({"status":"ok","scheduler_running":True})
        else:                     self._send({"error":"not found"},404)
    def do_POST(self):
        p = self.path.rstrip("/")
        body = self._read_body()
        if p == "/v1/units/execute":
            prompt = body.get("prompt","")
            result = f"[Worker] γ result for: {prompt[:60]}"
            print(f"  [worker] γ-unit executed: {prompt[:50]}...", flush=True)
            self._send({"result":result})
        elif p == "/v1/tasks/execute":
            title = body.get("title","task")
            prompt = body.get("prompt",title)
            units = [
                {"title":f"Worker step 1: {title[:30]}","result":f"Worker result A: analyzed {prompt[:40]}"},
                {"title":f"Worker step 2: {title[:30]}","result":f"Worker result B: implemented {prompt[:40]}"},
            ]
            compiled = "\n\n".join(f"## {u['title']}\n{u['result']}" for u in units)
            print(f"  [worker] βγ-task executed: {title[:40]} -> {len(units)} units", flush=True)
            self._send({"task_result":compiled,"units":units})
        else:
            self._send({"error":"not found"},404)

def stop_leader():
    if PID_PATH.exists():
        try:
            pid = int(PID_PATH.read_text().strip())
            os.kill(pid, signal.SIGTERM); time.sleep(1)
        except: pass
        PID_PATH.unlink(missing_ok=True)

def start_leader():
    env = os.environ.copy(); env["HUXLEYD_PORT"] = str(LEADER_PORT)
    proc = subprocess.Popen([sys.executable,"-m","harness.daemon"],
        stdout=open(LOG_PATH,"a"), stderr=subprocess.STDOUT, start_new_session=True)
    PID_PATH.write_text(str(proc.pid))
    deadline = time.time()+15
    while time.time()<deadline:
        try:
            import urllib.request
            urllib.request.urlopen(f"http://127.0.0.1:{LEADER_PORT}/health",timeout=1)
            print(f"  [leader] up on :{LEADER_PORT}", flush=True)
            return
        except: time.sleep(0.5)
    raise RuntimeError("leader failed to start")

def check_peers():
    import urllib.request
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{LEADER_PORT}/v1/swarm/peers", timeout=3)
        peers = json.loads(resp.read())
        return peers
    except: return []

if __name__ == "__main__":
    print("=== Swarm Delegation E2E Test ===", flush=True)

    # Stop stale leader
    stop_leader(); time.sleep(1)

    # Start worker HTTP server + periodic announcement thread
    worker_server = http.server.HTTPServer(("0.0.0.0", WORKER_PORT), WorkerHandler)
    threading.Thread(target=worker_server.serve_forever, daemon=True).start()
    print(f"[test] worker HTTP server :{WORKER_PORT}", flush=True)
    threading.Thread(target=announce_loop, args=(socket.gethostname(), WORKER_PORT, "βγ"), daemon=True).start()
    time.sleep(0.5)

    # Start leader daemon
    start_leader()
    time.sleep(3)

    # Wait for peer discovery
    print("[test] waiting for peer discovery...", flush=True)
    peers = []
    for i in range(12):
        peers = check_peers()
        if peers:
            print(f"  [test] peer discovered: {peers[0]['hostname']}:{peers[0]['port']} castes={peers[0]['castes']} load={peers[0]['load']}", flush=True)
            break
        time.sleep(2.5)
    if not peers:
        print("  [test] NO PEER DISCOVERED - delegation will fall back to local", flush=True)

    # Create an epic
    from harness.board import JobBoard, Task, Level
    board = JobBoard()
    epic = Task(level=Level.EPIC, title="Test Swarm Delegation",
                prompt="Build a Python CLI tool that counts words in a file. It should accept a filename argument, read the file, count words, and print the count.")
    board.create(epic)
    print(f"[test] created epic {epic.id[:8]}: {epic.title}", flush=True)

    # Wait for pipeline to complete
    start_time = time.time()
    print("[test] waiting up to 120s for pipeline...", flush=True)
    deadline = time.time() + 120
    while time.time() < deadline:
        t = board.get(epic.id)
        if t and t.state.name == "DONE":
            elapsed = time.time() - start_time
            print(f"[test] EPIC DONE after {elapsed:.0f}s", flush=True)
            break
        time.sleep(2)
    else:
        print("[test] TIMEOUT - epic not done", flush=True)

    # Wait a bit for compile step (post-DONE, Alpha generates project files)
    print("[test] waiting 15s for compile step...", flush=True)
    compile_deadline = time.time() + 15
    while time.time() < compile_deadline:
        log_text = LOG_PATH.read_text() if LOG_PATH.exists() else ""
        if "compile_ok" in log_text:
            print("[test] compile completed", flush=True)
            break
        time.sleep(2)
    else:
        print("[test] compile not seen in log (may still be running)", flush=True)

    # Report
    print("\n=== Results ===", flush=True)
    final = board.get(epic.id)
    if final:
        print(f"  Epic: {final.state.name}", flush=True)
        ptag = [t for t in final.tags if t.startswith("project:")]
        print(f"  Project: {ptag[0] if ptag else 'none'}", flush=True)

    tasks = board.children_of(epic.id)
    print(f"  Tasks: {len(tasks)}", flush=True)
    for t in tasks:
        units = board.children_of(t.id)
        print(f"    {t.id[:8]} {t.state.name:12} {t.title[:50]} ({len(units)} units)", flush=True)

    # Check logs for delegation
    log_text = LOG_PATH.read_text()
    delegates = [l for l in log_text.splitlines() if "delegate" in l.lower()]
    fallbacks = [l for l in log_text.splitlines() if "fallback" in l.lower()]
    gamma_done = [l for l in log_text.splitlines() if "gamma_done" in l]
    project = [l for l in log_text.splitlines() if "compile_ok" in l]
    print(f"\n--- Log Summary ---", flush=True)
    print(f"  delegate lines:  {len(delegates)}", flush=True)
    print(f"  fallback lines:  {len(fallbacks)}", flush=True)
    print(f"  gamma_done:      {len(gamma_done)}", flush=True)
    print(f"  compile_ok:      {len(project)}", flush=True)
    for d in delegates[-5:]:
        print(f"    {d}", flush=True)
    if not delegates and fallbacks:
        for f in fallbacks[-3:]:
            print(f"    {f}", flush=True)

    # Cleanup
    stop_leader()
    worker_server.shutdown()
    print("\n=== Done ===", flush=True)
