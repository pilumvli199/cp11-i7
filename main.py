#!/usr/bin/env python3
# main.py - Robust SmartAPI import + login (try multiple import names, dump site-packages candidates)

import os
import sys
import time
import datetime
import traceback

print("DEBUG: Python executable:", sys.executable)
print("DEBUG: initial sys.path[:8]:", sys.path[:8])

# --- helper to inspect site-packages for 'smart' related files ---
def inspect_site_packages():
    print("DEBUG: Inspecting sys.path for smartapi candidates...")
    candidates = []
    for p in sys.path:
        try:
            if not p or not os.path.isdir(p):
                continue
            # consider only site-packages-like paths (heuristic)
            lower = p.lower()
            if "site-packages" not in lower and "dist-packages" not in lower:
                # still check app root (it may shadow imports)
                pass
            for name in os.listdir(p):
                if "smart" in name.lower():
                    candidates.append(os.path.join(p, name))
        except Exception as e:
            # ignore permission/other issues
            continue
    print("DEBUG: Found candidates (first 200):")
    for c in candidates[:200]:
        try:
            print("  ", c)
        except Exception:
            print("  (path print error)")
    if not candidates:
        print("DEBUG: No smart* candidates found in sys.path entries scanned.")
    return candidates

# run inspection early so logs show it
cands = inspect_site_packages()

# --- Try multiple import names for smartapi ---
import importlib

possible_names = [
    "smartapi",
    "smartapi_python",
    "SmartApi",
    "smart_api",
    "smartapitools",
    "smartapi_python-1.5.5",  # unlikely, but include variants
]

SmartConnect = None
import_errors = {}

for name in possible_names:
    try:
        mod = importlib.import_module(name)
        print(f"DEBUG: Successful import as '{name}' -> {getattr(mod,'__file__', None)}")
        # try to find SmartConnect symbol
        if hasattr(mod, "SmartConnect"):
            SmartConnect = getattr(mod, "SmartConnect")
            print(f"DEBUG: Found SmartConnect in module '{name}'.")
            break
        # sometimes the package exposes submodule
        if hasattr(mod, "webSocket") and hasattr(mod, "webSocket"):
            # still attempt if class exists deeper
            try:
                sub = importlib.import_module(name + ".smartConnect")
                if hasattr(sub, "SmartConnect"):
                    SmartConnect = getattr(sub, "SmartConnect")
                    print(f"DEBUG: Found SmartConnect in submodule '{name}.smartConnect'.")
                    break
            except Exception:
                pass
        # if not found, keep going
        import_errors[name] = "imported_but_no_SmartConnect"
    except Exception as e:
        import_errors[name] = f"{type(e).__name__}: {e}"

# If not found yet, try scanning candidates for importable package paths and attempt import by path
if SmartConnect is None and cands:
    for path in cands:
        # if path is a package dir, try to add its parent to sys.path and import basename
        base = os.path.basename(path)
        parent = os.path.dirname(path)
        modname = os.path.splitext(base)[0]
        try:
            if parent not in sys.path:
                sys.path.insert(0, parent)
            mod = importlib.import_module(modname)
            print(f"DEBUG: Imported by path basename '{modname}' -> {getattr(mod,'__file__',None)}")
            if hasattr(mod, "SmartConnect"):
                SmartConnect = getattr(mod, "SmartConnect")
                print(f"DEBUG: Found SmartConnect in module imported from path '{path}'.")
                break
        except Exception as e:
            import_errors[f"path::{path}"] = f"{type(e).__name__}: {e}"
            # continue

# After tries, report summary
print("DEBUG: import_errors summary (first 200):")
count = 0
for k, v in import_errors.items():
    if count > 200:
        break
    print("  ", k, "->", v)
    count += 1

if SmartConnect is None:
    print("❌ Could not locate SmartConnect via tried imports. Final sys.path[:6]:", sys.path[:6])
    print("---- End of import attempts. Paste these logs and the site-packages candidates above. ----")
    # helpful pip freeze output for diagnosing build vs runtime mismatch
    try:
        import subprocess
        print("\n---- pip freeze ----")
        subprocess.call([sys.executable, "-m", "pip", "freeze"])
    except Exception:
        pass
    # exit with non-zero so deployment log shows failure
    sys.exit(1)

# If we reached here, we have SmartConnect
print("✅ SmartConnect resolved:", SmartConnect)

# ---------- proceed to load dotenv, creds and login ----------
try:
    from dotenv import load_dotenv
except Exception:
    print("WARN: python-dotenv not importable. Continuing (will rely on env variables).")

load_dotenv()

SMARTAPI_API_KEY = os.getenv("SMARTAPI_API_KEY", "").strip()
SMARTAPI_CLIENT_CODE = os.getenv("SMARTAPI_CLIENT_CODE", "").strip()
SMARTAPI_MPIN = os.getenv("SMARTAPI_MPIN", "").strip()
SMARTAPI_PASSWORD = os.getenv("SMARTAPI_PASSWORD", "").strip()
SMARTAPI_TOTP_SECRET = os.getenv("SMARTAPI_TOTP_SECRET", "").strip()

print("DEBUG: SMARTAPI_CLIENT_CODE present?:", bool(SMARTAPI_CLIENT_CODE))
print("DEBUG: SMARTAPI_MPIN present?:", bool(SMARTAPI_MPIN))
print("DEBUG: SMARTAPI_PASSWORD present?:", bool(SMARTAPI_PASSWORD))
print("DEBUG: SMARTAPI_TOTP_SECRET present?:", bool(SMARTAPI_TOTP_SECRET))

if not SMARTAPI_CLIENT_CODE:
    print("❌ Missing SMARTAPI_CLIENT_CODE. Set env and redeploy.")
    sys.exit(1)

# create SmartConnect instance (use SmartConnect from resolved module)
try:
    # try constructor with api_key keyword first
    try:
        s = SmartConnect(api_key=SMARTAPI_API_KEY)
    except TypeError:
        s = SmartConnect(SMARTAPI_API_KEY)
except Exception:
    print("❌ SmartConnect init failed. Traceback:")
    traceback.print_exc()
    sys.exit(1)

# TOTP helper
def login_try_password_totp(s):
    import pyotp
    if not SMARTAPI_PASSWORD or not SMARTAPI_TOTP_SECRET:
        return None
    totp = pyotp.TOTP(SMARTAPI_TOTP_SECRET)
    print("DEBUG: Local epoch:", int(time.time()))
    print("DEBUG: Current TOTP:", totp.now())
    epoch = int(time.time())
    for offset in (-30, 0, 30):
        try:
            code = totp.at(epoch + offset)
        except Exception:
            code = None
        if not code:
            continue
        try:
            print("DEBUG: Trying totp:", code, "offset", offset)
            resp = s.generateSession(SMARTAPI_CLIENT_CODE, SMARTAPI_PASSWORD, str(code).zfill(6))
            print("Login resp:", resp)
            if isinstance(resp, dict) and resp.get("status"):
                return resp
        except Exception:
            traceback.print_exc()
    return None

def login_try_mpin(s):
    if not SMARTAPI_MPIN:
        return None
    try:
        try:
            resp = s.generateSession(SMARTAPI_CLIENT_CODE, SMARTAPI_MPIN, SMARTAPI_API_KEY)
        except TypeError:
            resp = s.generateSession(SMARTAPI_CLIENT_CODE, SMARTAPI_MPIN)
        print("MPIN login resp:", resp)
        return resp
    except Exception:
        traceback.print_exc()
        return None

def main():
    print("Starting login attempts...")
    resp = login_try_mpin(s)
    if resp and isinstance(resp, dict) and resp.get("status"):
        print("✅ MPIN login successful.")
        return
    resp2 = login_try_password_totp(s)
    if resp2 and isinstance(resp2, dict) and resp2.get("status"):
        print("✅ Password+TOTP login successful.")
        return
    print("❌ Login failed. See above logs.")
    sys.exit(1)

if __name__ == "__main__":
    main()
