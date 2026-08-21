#!/usr/bin/env python3
"""Runner auto-register v3 — GitHub Actions pe (naya runner IP har run).
v3 (2026-08-21): BATCHED GH API — 1 run me N accounts, sirf ~7 GH calls
(pahle ~10 calls/account the -> ab ~1-2 calls/account). GitHub rate-limit
khatam hone ki problem SOLVED.

Flow: inbox se N fresh tokens claim (1 read + 1 write) -> N register
(kartoons API, 12s gap) -> outbox me SAB ek saath append (1 read + 1 write)
-> status 1 baar. Indian names file se (human-like accounts).
"""
import json, os, random, string, time, urllib.request, urllib.error, base64, re

TOKEN = os.environ.get("TOKEN", "")
GH_PAT = os.environ.get("GH_PAT", "")
GH_REPO = (os.environ.get("GH_REPO", "") or os.environ.get("HUB_REPO", "") or "voughtx/kts-mailbox").strip()
NAMES_URL = os.environ.get("NAMES_URL", f"https://raw.githubusercontent.com/{GH_REPO}/main/names.txt")
NAMES_FILE = os.environ.get("NAMES_FILE", "names.txt")
MAX_ACCOUNTS = int(os.environ.get("MAX_ACCOUNTS", "5") or 5)  # v3: 5/run (naya IP, 12s gap = safe)
GAP = float(os.environ.get("GAP", "12") or 12)  # accounts ke beech gap
UA = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"
HDRS = {"User-Agent": UA, "Content-Type": "application/json",
        "Origin": "https://kartoons.me", "Referer": "https://kartoons.me/",
        "X-Skip-Challenge": "true"}
MAX_AGE = 240  # 4 min fresh limit

_NAMES = []


def load_names():
    global _NAMES
    if _NAMES:
        return _NAMES
    content = ""
    try:
        if NAMES_URL:
            rq = urllib.request.Request(NAMES_URL, headers={"User-Agent": "kts-runner"})
            content = urllib.request.urlopen(rq, timeout=25).read().decode(errors="ignore")
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
            uname, full = parts[4], parts[1]
        elif len(parts) == 1 and "@" in line:
            uname = line.split("@")[0]
            full = " ".join(w.capitalize() for w in uname.replace(".", " ").replace("_", " ").split()[:2]) or uname
        else:
            continue
        if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9._-]{2,}", uname):
            _NAMES.append((uname, full))
    return _NAMES


def api_headers(extra=None):
    h = {"Authorization": "token " + GH_PAT, "User-Agent": "kts-runner",
         "Accept": "application/vnd.github+json"}
    if extra:
        h.update(extra)
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
    if sha:
        data["sha"] = sha
    rq = urllib.request.Request(f"https://api.github.com/repos/{GH_REPO}/contents/{path}",
                                data=json.dumps(data).encode(), method="PUT",
                                headers=api_headers({"Content-Type": "application/json"}))
    try:
        with urllib.request.urlopen(rq, timeout=20) as r:
            return r.status in (200, 201)
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return False  # race
        raise


def claim_fresh_tokens(n):
    """1 read + 1 write: inbox se sabse naye N fresh tokens claim karo (remove bhi)."""
    sha, content = gh_get("inbox.txt")
    now = time.time()
    fresh = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" in line[:12]:
            ep_s, tok = line.split(":", 1)
            if ep_s.isdigit() and now - int(ep_s) <= MAX_AGE:
                fresh.append((int(ep_s), tok))
    fresh.sort(reverse=True)  # naye pehle
    picked = [t for _, t in fresh[:n]]
    if not picked:
        return []
    # inbox se sab claimed hatado (1 write)
    keep = [l for l in content.splitlines() if l.strip() and not any(t in l for t in picked)]
    gh_put("inbox.txt", "\n".join(keep).strip() + ("\n" if keep else ""), sha)
    print(f"[v3] claimed {len(picked)} tokens (inbox {len(fresh)} fresh)", flush=True)
    return picked


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
        return None, f"HTTP {e.code}: {e.read().decode()[:150]}"


def main():
    print("runner IP:", urllib.request.urlopen("https://api.ipify.org", timeout=10).read().decode(), flush=True)
    print(f"mode: {'manual' if TOKEN else 'auto'} | max: {MAX_ACCOUNTS} | GH calls: ~7/run", flush=True)
    names = load_names()
    print("names:", len(names), flush=True)

    if TOKEN:
        tokens_to_try = [TOKEN]
    else:
        tokens_to_try = claim_fresh_tokens(MAX_ACCOUNTS)
        if not tokens_to_try:
            print("NO FRESH TOKEN in inbox — nothing to do", flush=True)
            return

    # used names: 1 outbox read (ek baar)
    used = set()
    try:
        _, oc = gh_get("runner_outbox.txt")
        for m in re.finditer(r"username:\s*(\S+)", oc):
            used.add(m.group(1))
    except Exception:
        pass

    made = []
    for i, tok in enumerate(tokens_to_try, 1):
        fresh = [n for n in names if n[0] not in used]
        if not fresh:
            break
        uname, full = random.choice(fresh)
        used.add(uname)
        print(f"try {i}/{len(tokens_to_try)}: {uname}...", flush=True)
        acc, err = req_register(tok, uname, full)
        if err or not acc or not acc.get("jwt"):
            print("  fail:", (err or "no jwt")[:120], flush=True)
            continue
        made.append(acc)
        print(f"  ✅ {uname} ({full})", flush=True)
        time.sleep(GAP)

    # outbox append: 1 read + 1 write (sab ek saath)
    if made:
        try:
            sha, old = gh_get("runner_outbox.txt")
            recs = []
            for a in made:
                recs.append(f"\n===\nusername: {a['username']}\nfull_name: {a['full_name']}\n"
                            f"password: {a['password']}\nemail: {a['email']}\njwt: {a['jwt']}\n"
                            f"source: github-runner\n")
            new_content = (old.rstrip() + "\n" + "".join(recs).lstrip("\n")) if old.strip() else "".join(recs).lstrip("\n")
            gh_put("runner_outbox.txt", new_content.rstrip() + "\n", sha)
        except Exception as e:
            print("outbox write fail:", str(e)[:80], flush=True)

        # status: 1 read + 1 write
        try:
            sha2, _ = gh_get("runner_status.txt")
            n = (old.count("username:") if 'old' in dir() else 0) + len(made)
            gh_put("runner_status.txt", f"last_run: {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}\ntotal_jwts: {n}", sha2)
        except Exception:
            pass

    print(f"DONE: {len(made)}/{len(tokens_to_try)} accounts (GH calls ~7)", flush=True)


if __name__ == "__main__":
    main()
