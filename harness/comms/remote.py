import json
import urllib.request
import urllib.error
from urllib.error import HTTPError


def post_to_peer(addr: str, port: int, path: str, body: dict, timeout: int = 30) -> dict | None:
    url = f"http://{addr}:{port}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = e.read()
        return json.loads(body) if body else {"error": str(e.code)}
    except (urllib.error.URLError, ConnectionError, OSError, json.JSONDecodeError):
        return None
