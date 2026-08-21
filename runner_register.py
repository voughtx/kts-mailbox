#!/usr/bin/env python3
"""Runner auto-register v2 — GitHub Actions pe chalta hai (naya runner IP har run).
AUTO MODE: inbox.txt se fresh token -> register (INDIAN DUMMY NAMES file se
username+email — human-like, mailinator nahi) -> JWT -> runner_outbox.txt.
v2 (2026-08-21): indian_dummy_gmail_ids_10000.txt se random name pick,
used names outbox se skip (dobara use nahi), MAX_ACCOUNTS env se cap
(pehle chhota batch — testing ke baad scale up).
"""
import json, os, random, string, time, urllib.request, urllib.error, base64, re

TOKEN = os.environ.get("TOKEN", "")
GH_PAT = os.environ.get("GH_PAT", "")
GH_REPO = os.environ.get("GH_REPO", "")
NAMES_URL = os.environ.get("NAMES_URL", "")  # raw gist/repo link to names file (optional)
NAMES_FILE = os.environ.get("NAMES_FILE", "names.txt")  # local fallback
MAX_ACCOUNTS = int(os.environ.get("MAX_ACCOUNTS", "3") or 3)  # cap per run (chhota pehle)
UA = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"
HDRS = {"User-Agent": UA, "Content-Type": "application/json",
        "Origin": "https://kartoons.me", "Referer": "https://kartoons.me/",
        "X-Skip-Challenge": "true"}
MAX_AGE = 240  # 4 min fresh limit

# ============ INDIAN NAMES LOAD ============
_NAMES = []


def load_names():
    """names file se (username, full_name) pairs. Pehle NAMES_URL, warna local file."""
    global _NAMES
    if _NAMES:
        return _NAMES
    content = ""
    try:
        if NAMES_URL:
            rq = urllib.request.Request(NAMES_URL, headers={"User-Agent": "kts-runner"})
            content = urllib.request.urlopen(rq, timeout=20).read().decode(errors="ignore")
        elif os.path.exists(NAMES_FILE):
            content = open(NAMES_FILE, encoding="utf-8", errors="ignore").read()
    except Exception as e:
        print("names load err:", str(e)[:80], flush=True)
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("S.No.") or line.startswith("="):
            continue
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) >= 6:
            uname = parts[4]
            full = parts[1]
        elif len(parts) == 1 and "@" in line:
            # sirf email list format
            uname = line.split("@")[0]
            full = " ".join(w.capitalize() for w in uname.replace(".", " ").replace("_", " ").split()[:2]) or uname
        else:
            continue
        if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9._-]{2,}", uname):
            _NAMES.append((uname, full))
    return _NAMES


def used_usernames():
    """runner_outbox.txt se pehle use hue usernames (dobara na ho)."""
    used = set()
    try:
        _, content = gh_get("runner_outbox.txt")
        for m in re.finditer(r"username:\s*(\S+)", content):
            used.add(m.group(1))
    except Exception:
        pass
    return used


def pick_name():
    """Random fresh (username, full_name) — used wale skip."""
    names = load_names()
    if not names:
        return None, None
    used = used_usernames()
    fresh = [n for n in names if n[0] not in used]
    if not fresh:
        print("SABHI names used — file khatam!", flush=True)
        return None, None
    return random.choice(fresh)


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
            if best is None:
                best = (int(now), line)
    return best


def remove_token_from_inbox(tok_to_remove):
    try:
        sha, content = gh_get("inbox.txt")
        lines = [l for l in content.splitlines() if l.strip()]
        keep = [l for l in lines if tok_to_remove not in l]
        new_content = "\n".join(keep) + ("\n" if keep else "")
        gh_put("inbox.txt", new_content, sha)
    except Exception as e:
        print("inbox cleanup fail:", str(e)[:60], flush=True)


def req_register(token, uname, full_name):
    password = "P@ss" + "".join(random.choices(string.ascii_letters + string.digits, k=14)) + "!"
    email = f"{uname}@gmail.com"
    body = json.dumps({"username": uname, "password": password,
                       "email": email, "turnstile_token": token}).encode()
    rq = urllib.request.Request("https://api.kartoons.me/api/auth/register",
                                data=body, method="POST", headers=HDRS)
    try:
        with urllib.request.urlopen(rq, timeout=30) as resp:
            d = json.loads(resp.read().decode())
            dd = d.get("data") or {}
            jwt = dd.get("access_token") or dd.get("token") or dd.get("jwt")
            return {"ok": True, "username": uname, "full_name": full_name,
                    "password": password, "email": email,
                    "jwt": jwt or "", "status": resp.status}, None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()[:200]}"


def update_status():
    try:
        sha, old = gh_get("runner_status.txt")
        osha, ocontent = gh_get("runner_outbox.txt")
        n = ocontent.count("username:")
        text = f"last_run: {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}\ntotal_jwts: {n}"
        gh_put("runner_status.txt", text, sha)
    except Exception as e:
        print("status update fail:", str(e)[:60], flush=True)


def main():
    print("runner IP:", urllib.request.urlopen("https://api.ipify.org", timeout=10).read().decode(), flush=True)
    print("mode:", "manual" if TOKEN else "auto", "| max accounts:", MAX_ACCOUNTS, flush=True)
    n_names = len(load_names())
    print("names loaded:", n_names, flush=True)

    if TOKEN:
        tokens_to_try = [TOKEN]
    else:
        got = get_latest_fresh_token()
        if not got:
            print("NO FRESH TOKEN in inbox — nothing to do (tokens ruk gaye = runner stop)", flush=True)
            return
        tokens_to_try = []
        for _ in range(MAX_ACCOUNTS):
            g = get_latest_fresh_token()
            if not g:
                break
            ep, tk = g
            tokens_to_try.append(tk)
            remove_token_from_inbox(tk)

    made = 0
    for i, tok in enumerate(tokens_to_try, 1):
        if made >= MAX_ACCOUNTS:
            print(f"cap {MAX_ACCOUNTS} reached — stop", flush=True)
            break
        uname, full = pick_name()
        if not uname:
            break
        print(f"try {i}/{len(tokens_to_try)}: register as {uname}...", flush=True)
        acc, err = req_register(tok, uname, full)
        if err or not acc or not acc.get("jwt"):
            print("  fail:", (err or "no jwt")[:120], flush=True)
            continue
        print(f"  ✅ {acc['username']} ({acc['full_name']})", flush=True)
        rec = (f"\n===\nusername: {acc['username']}\nfull_name: {acc['full_name']}\n"
               f"password: {acc['password']}\nemail: {acc['email']}\njwt: {acc['jwt']}\n"
               f"source: github-runner\n")
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
        time.sleep(12)  # BATCH gap — ek runner IP se 2 accounts 12s gap

    if made:
        print(f"DONE: {made} JWT banaye is run me", flush=True)
    else:
        print("No account bana — tokens expire ho gaye honge. Naye bhejo.", flush=True)


if __name__ == "__main__":
    main()
