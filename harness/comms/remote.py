import json
import urllib.request
import urllib.error


def post_to_peer(addr: str, port: int, path: str, body: dict, timeout: int = 30) -> dict | None:
    url = f"http://{addr}:{port}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
            print(f"γ|debug|post_to_peer|ok|{url}|{resp.status}", flush=True)
            return result
    except urllib.error.HTTPError as e:
        body = e.read()
        print(f"γ|debug|post_to_peer|http_err|{url}|{e.code}|{body[:100]}", flush=True)
        return json.loads(body) if body else {"error": str(e.code)}
    except urllib.error.URLError as e:
        print(f"γ|debug|post_to_peer|url_err|{url}|{e.reason}", flush=True)
        return None
    except (ConnectionError, OSError) as e:
        print(f"γ|debug|post_to_peer|conn_err|{url}|{e}", flush=True)
        return None
    except json.JSONDecodeError as e:
        print(f"γ|debug|post_to_peer|json_err|{url}|{e}", flush=True)
        return None
