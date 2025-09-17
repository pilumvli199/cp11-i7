#!/usr/bin/env python3
# main.py - Fixed MPIN usage + safe backoff + robust TOTP handling

import os
import sys
import time
import datetime
import traceback
import importlib

print("DEBUG: Python executable:", sys.executable)
print("DEBUG: initial sys.path[:8]:", sys.path[:8])

# Minimal runtime ensure (convenience)
def runtime_ensure(pkgs_map):
    import subprocess
    to_install = []
    for pip_pkg, mods in pkgs_map.items():
        ok = False
        for m in mods:
            try:
                importlib.import_module(m)
                ok = True
                break
            except Exception:
                continue
        if not ok:
            to_install.append(pip_pkg)
    if not to_install:
        return True
    try:
        for p in to_install:
            print("INFO: pip installing", p)
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", p])
        return True
    except Exception as e:
        print("WARN: runtime install failed:", e)
        return False

runtime_ensure({
    "python-dotenv": ["dotenv"],
    "pyotp": ["pyotp"],
    "smartapi-python": ["SmartApi", "smartapi"],
})

# inspect site-packages candidates (helpful for debug)
def inspect_site_packages():
    import os
    print("DEBUG: Inspecting sys.path for smart* candidates...")
    candidates = []
    for p in sys.path:
        try:
            if not p or not os.path.isdir(p):
                continue
            for name in os.listdir(p):
                if "smart" in name.lower():
                    candidates.append(os.path.join(p, name))
        except Exception:
            pass
    for c in candidates[:200]:
        print("  ", c)
    return candidates

inspect_site_packages()

# Try flexible imports
SmartConnect = None
possible_names = ["smartapi", "SmartApi", "smartapi_python", "smart_api"]
for name in possible_names:
    try:
        mod = importlib.import_module(name)
        print(f"DEBUG: Imported {name} -> {getattr(mod,'__file__', None)}")
        if hasattr(mod, "SmartConnect"):
            SmartConnect = getattr(mod, "SmartConnect")
            print(f"DEBUG: Found SmartConnect in {name}")
            break
    except Exception as e:
        # ignore and continue
        pass

if SmartConnect is None:
    print("❌ Could not import SmartConnect. Aborting.")
    try:
        import subprocess
        print("\n---- pip freeze ----")
        subprocess.call([sys.executable, "-m", "pip", "freeze"])
    except Exception:
        pass
    sys.exit(1)

# dotenv + pyotp
try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None
try:
    import pyotp
except Exception:
    pyotp = None

if load_dotenv:
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
    print("❌ Missing SMARTAPI_CLIENT_CODE. Set env var and redeploy.")
    sys.exit(1)

# create SmartConnect instance
try:
    try:
        s = SmartConnect(api_key=SMARTAPI_API_KEY)
    except TypeError:
        s = SmartConnect(SMARTAPI_API_KEY)
except Exception:
    print("❌ SmartConnect init failed. Traceback:")
    traceback.print_exc()
    sys.exit(1)

# Utility: sleep with exponential backoff (capped)
def backoff_sleep(attempt, base=1.0, cap=16.0):
    delay = min(cap, base * (2 ** attempt))
    print(f"DEBUG: Backoff sleeping {delay:.1f}s (attempt {attempt})")
    time.sleep(delay)

# Helper: try MPIN login correctly (do NOT pass API key as third arg)
def try_login_mpin(max_retries=3):
    if not SMARTAPI_MPIN:
        return None
    attempt = 0
    while attempt < max_retries:
        try:
            print("DEBUG: Trying MPIN login (call with 2 args only)...")
            # IMPORTANT: call generateSession with (clientcode, mpin) ONLY
            resp = s.generateSession(SMARTAPI_CLIENT_CODE, SMARTAPI_MPIN)
            print("Login response (MPIN):", resp)
            return resp
        except Exception as e:
            # handle known error messages / rate limit
            msg = str(e)
            print("Exception during MPIN login:", msg)
            # if rate-limited, backoff more
            if "exceeding access rate" in msg.lower() or "access denied" in msg.lower():
                backoff_sleep(attempt, base=2.0, cap=60.0)
            else:
                backoff_sleep(attempt)
            attempt += 1
    return None

# Helper: try password + TOTP (only when allowed)
def try_login_password_totp(max_retries=2):
    if not SMARTAPI_PASSWORD or not SMARTAPI_TOTP_SECRET:
        print("DEBUG: password or totp secret missing - skipping pwd+totp")
        return None
    if pyotp is None:
        print("WARN: pyotp not installed - cannot generate TOTP")
        return None

    totp_obj = pyotp.TOTP(SMARTAPI_TOTP_SECRET)
    # try current and ±30s, but do not hammer server: include small sleeps
    offsets = [-30, 0, 30]
    for i, offset in enumerate(offsets):
        try:
            code = totp_obj.at(int(time.time()) + offset)
        except Exception as e:
            print("WARN: pyotp.at() error:", e)
            continue
        code_str = str(code).zfill(6)
        try:
            print(f"DEBUG: Trying password+totp with totp={code_str} (offset {offset})")
            resp = s.generateSession(SMARTAPI_CLIENT_CODE, SMARTAPI_PASSWORD, code_str)
            print("Login response (pwd+totp):", resp)
            # If server explicitly says password login not allowed, stop further tries
            if isinstance(resp, dict):
                if resp.get("message") and "LoginbyPassword is not allowed" in str(resp.get("message")):
                    print("DEBUG: Server forbids password login; stop password attempts")
                    return resp
                if resp.get("status"):
                    return resp
            # small sleep to avoid rate-limit
            time.sleep(1.0)
        except Exception as e:
            err = str(e)
            print("Exception during pwd+totp attempt:", err)
            # JSON decode error sometimes indicates a plain-text error like "Access denied..." — respect backoff
            if "exceeding access rate" in err.lower() or "access denied" in err.lower():
                print("DEBUG: Detected rate-limit message from server. Backing off.")
                time.sleep(5 + i * 5)
            else:
                time.sleep(1.0)
            continue
    return None

# Main flow
def main():
    print("Starting login flow at", datetime.datetime.utcnow().isoformat())
    # 1) Try MPIN first (server prefers MPIN)
    resp = try_login_mpin(max_retries=4)
    if resp and isinstance(resp, dict) and resp.get("status"):
        print("✅ MPIN login successful.")
        return

    # If MPIN failed or not provided, try password+totp
    resp2 = try_login_password_totp(max_retries=2)
    if resp2 and isinstance(resp2, dict) and resp2.get("status"):
        print("✅ Password+TOTP login successful.")
        return

    # if server explicitly forbids password login, and MPIN failed, surface the server messages
    print("❌ Login failed. MPIN resp:", resp, "pwd+totp resp:", resp2)
    # If we hit rate-limit, avoid immediate restart; exit so orchestrator can restart later
    sys.exit(1)

if __name__ == "__main__":
    main()
