#!/usr/bin/env python3
"""Runner-side register — GitHub Actions pe chalta hai (naya runner IP).
Use: TOKEN=<fresh> python3 runner_register.py
Register try -> JWT -> runner_outbox.txt (GitHub) me save + print."""
import json, os, random, string, time, urllib.request, urllib.error, base64

TOKEN = os.environ.get("TOKEN", "")
GH_PAT = os.environ.get("GH_PAT", "")
GH_REPO = os.environ.get("GH_REPO", "")
UA = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"
HDRS = {"User-Agent": UA, "Content-Type": "application/json",
        "Origin": "https://kartoons.me", "Referer": "https://kartoons.me/",
        "X-Skip-Challenge": "true"}

def api_headers(extra=None):
    h = {"Authorization": "token " + GH_PAT, "User-Agent": "kts-runner"}
    if extra: h.update(extra)
    return h

def gh_get(path):
    rq = urllib.request.Request(f"https://api.github.com/repos/{GH_REPO}/contents/{path}",
                                headers=api_headers())
    try:
        with urllib.request.urlopen(rq, timeout=20) as r:
            d = json.loads(r.read().decode())
            return d.get("sha"), base64.b64decode(d["content"]).decode(errors="ignore")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, ""
        raise

def gh_put(path, content, sha=None):
    data = {"message": f"update {path}", "content": base64.b64encode(content.encode()).decode()}
    if sha: data["sha"] = sha
    rq = urllib.request.Request(f"https://api.github.com/repos/{GH_REPO}/contents/{path}",
                                data=json.dumps(data).encode(), method="PUT",
                                headers=api_headers({"Content-Type": "application/json"}))
    with urllib.request.urlopen(rq, timeout=20) as r:
        return r.status in (200, 201)

def req_register(token):
    username = "u" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    password = "P@ss" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10)) + "!"
    email = f"{username}@mailinator.com"
    body = json.dumps({"username": username, "password": password,
                       "email": email, "turnstile_token": token}).encode()
    rq = urllib.request.Request("https://api.kartoons.me/api/auth/register",
                                data=body, method="POST", headers=HDRS)
    try:
        with urllib.request.urlopen(rq, timeout=30) as resp:
            d = json.loads(resp.read().decode())
            dd = d.get("data") or {}
            jwt = dd.get("access_token") or dd.get("token") or dd.get("jwt")
            return {"ok": True, "username": username, "password": password, "email": email,
                    "jwt": jwt or "", "status": resp.status}, None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()[:200]}"

def main():
    print("runner IP:", urllib.request.urlopen("https://api.ipify.org", timeout=10).read().decode(), flush=True)
    print("token len:", len(TOKEN), flush=True)
    acc, err = req_register(TOKEN)
    if err or not acc or not acc.get("jwt"):
        print("REGISTER FAIL:", err or "no jwt", flush=True)
        raise SystemExit(1)
    print("REGISTER SUCCESS:", acc["username"], flush=True)
    print("JWT:", acc["jwt"][:40] + "...", flush=True)
    # save to runner_outbox.txt
    try:
        sha, old = gh_get("runner_outbox.txt")
        rec = f"\n===\nusername: {acc['username']}\npassword: {acc['password']}\nemail: {acc['email']}\njwt: {acc['jwt']}\nsource: github-runner\n"
        gh_put("runner_outbox.txt", (old + rec).strip() + "\n", sha)
        print("outbox updated", flush=True)
    except Exception as e:
        print("outbox fail:", e, flush=True)

if __name__ == "__main__":
    main()
