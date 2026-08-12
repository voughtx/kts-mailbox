#!/usr/bin/env python3
"""Runner auto-register — GitHub Actions pe chalta hai (naya runner IP har run).
AUTO MODE: agar TOKEN env na diya ho toh inbox.txt se latest fresh token khud
le leta hai -> register -> JWT -> runner_outbox.txt me save -> inbox se token hata deta hai.
Concurrency group workflow me hai taaki ek time pe sirf 1 run (outbox race fix)."""
import json, os, random, string, time, urllib.request, urllib.error, base64

TOKEN = os.environ.get("TOKEN", "")
GH_PAT = os.environ.get("GH_PAT", "")
GH_REPO = os.environ.get("GH_REPO", "")
UA = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"
HDRS = {"User-Agent": UA, "Content-Type": "application/json",
        "Origin": "https://kartoons.me", "Referer": "https://kartoons.me/",
        "X-Skip-Challenge": "true"}
MAX_AGE = 240  # 4 min fresh limit

def api_headers(extra=None):
    h = {"Authorization": "token " + GH_PAT, "User-Agent": "kts-runner",
         "Accept": "application/vnd.github+json"}
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
    try:
        with urllib.request.urlopen(rq, timeout=20) as r:
            return r.status in (200, 201)
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return False  # conflict — race
        raise

def get_latest_fresh_token():
    """inbox.txt se sabse naya fresh token (+ timestamp). Returns (epoch, token) ya None."""
    sha, content = gh_get("inbox.txt")
    now = time.time()
    best = None
    for line in content.splitlines():
        line = line.strip()
        if not line: continue
        if ":" in line[:12]:
            ep_s, tok = line.split(":", 1)
            if ep_s.isdigit():
                ep = int(ep_s)
                if now - ep <= MAX_AGE:
                    if best is None or ep > best[0]:
                        best = (ep, tok)
        else:
            # no timestamp (old format) — treat fresh
            if best is None:
                best = (int(now), line)
    return best

def remove_token_from_inbox(tok_to_remove):
    """inbox.txt se processed token hatao."""
    try:
        sha, content = gh_get("inbox.txt")
        lines = [l for l in content.splitlines() if l.strip()]
        keep = [l for l in lines if tok_to_remove not in l]
        new_content = "\n".join(keep) + ("\n" if keep else "")
        gh_put("inbox.txt", new_content, sha)
    except Exception as e:
        print("inbox cleanup fail:", e, flush=True)

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

def update_status():
    """runner_status.txt me count + last run — user GitHub pe dekh sakta hai"""
    try:
        sha, old = gh_get("runner_status.txt")
        osha, ocontent = gh_get("runner_outbox.txt")
        n = ocontent.count("username:")
        text = f"last_run: {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}\ntotal_jwts: {n}"
        gh_put("runner_status.txt", text, sha)
    except Exception as e:
        print("status update fail:", e, flush=True)

def main():
    print("runner IP:", urllib.request.urlopen("https://api.ipify.org", timeout=10).read().decode(), flush=True)
    print("mode:", "manual" if TOKEN else "auto", flush=True)

    if TOKEN:
        # manual dispatch: 1 token, 1 try
        tokens_to_try = [TOKEN]
    else:
        # AUTO: inbox se fresh tokens (max 3 retry — 3 token try, agar sab fail toh stop)
        got = get_latest_fresh_token()
        if not got:
            print("NO FRESH TOKEN in inbox — nothing to do (tokens ruk gaye = runner stop)", flush=True)
            return
        tokens_to_try = []
        for _ in range(3):
            g = get_latest_fresh_token()
            if not g:
                break
            ep, tk = g
            tokens_to_try.append(tk)
            remove_token_from_inbox(tk)  # abhi claim kiya

    made = 0
    for i, tok in enumerate(tokens_to_try, 1):
        print(f"try {i}/{len(tokens_to_try)}: register...", flush=True)
        acc, err = req_register(tok)
        if err or not acc or not acc.get("jwt"):
            print("  fail:", (err or "no jwt")[:120], flush=True)
            continue
        # SUCCESS
        print("  ✅", acc["username"], flush=True)
        rec = f"\n===\nusername: {acc['username']}\npassword: {acc['password']}\nemail: {acc['email']}\njwt: {acc['jwt']}\nsource: github-runner\n"
        for attempt in range(3):
            try:
                sha, old = gh_get("runner_outbox.txt")
                if gh_put("runner_outbox.txt", (old + rec).strip() + "\n", sha):
                    break
            except Exception:
                pass
            time.sleep(2)
        made += 1
        update_status()
        time.sleep(2)

    if made:
        print(f"DONE: {made} JWT banaye is run me", flush=True)
    else:
        print("No account bana — tokens expire ho gaye honge. Naye bhejo.", flush=True)

if __name__ == "__main__":
    main()
