#!/usr/bin/env python3
# main.py - Fixed: MPIN login now sends TOTP as well (mpin + totp).
# Replace your existing main.py with this.

import os
import sys
import time
import datetime
import traceback
import importlib

print("DEBUG: Python executable:", sys.executable)
print("DEBUG: initial sys.path[:8]:", sys.path[:8])

# try runtime ensure (convenience)
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
    print("INFO: Attempting runtime install for:", to_install)
    try:
        for pkg in to_install:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", pkg])
        return True
    except Exception as e:
        print("WARN: runtime install failed:", e)
        traceback.print_exc()
        return False

runtime_ensure({
    "python-dotenv": ["dotenv"],
    "pyotp": ["pyotp"],
    "smartapi-python": ["SmartApi", "smartapi"],
})

# inspect site-packages for debug
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

# Flexible import for SmartConnect
SmartConnect = None
for candidate in ("smartapi", "SmartApi", "smartapi_python", "smart_api"):
    try:
        mod = importlib.import_module(candidate)
        print(f"DEBUG: Imported {candidate} -> {getattr(mod,'__file__', None)}")
        if hasattr(mod, "SmartConnect"):
            SmartConnect = getattr(mod, "SmartConnect")
            print(f"DEBUG: Found SmartConnect in {candidate}")
            break
    except Exception:
        continue

if SmartConnect is None:
    print("❌ Could not import SmartConnect. Exiting.")
    try:
        import subprocess
        print("\n---- pip freeze ----")
        subprocess.call([sys.executable, "-m", "pip", "freeze"])
    except Exception:
        pass
    sys.exit(1)

# dotenv & pyotp
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

# load environment
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

# instantiate SmartConnect
try:
    try:
        s = SmartConnect(api_key=SMARTAPI_API_KEY)
    except TypeError:
        s = SmartConnect(SMARTAPI_API_KEY)
except Exception:
    print("❌ SmartConnect init failed. Traceback:")
    traceback.print_exc()
    sys.exit(1)

# backoff helper
def backoff_sleep(attempt, base=1.0, cap=20.0):
    delay = min(cap, base * (2 ** attempt))
    print(f"DEBUG: Backoff sleeping {delay:.1f}s (attempt {attempt})")
    time.sleep(delay)

# generate totp candidate list (current ± 30s)
def totp_candidates(secret):
    if not pyotp or not secret:
        return []
    epoch = int(time.time())
    codes = []
    for offset in (-30, 0, 30):
        try:
            codes.append(str(pyotp.TOTP(secret).at(epoch + offset)).zfill(6))
        except Exception:
            codes.append(None)
    # unique and preserve order
    seen = set()
    out = []
    for c in codes:
        if c and c not in seen:
            out.append(c)
            seen.add(c)
    return out

# MPIN login: now must send mpin + totp (SmartConnect requires totp arg)
def try_login_mpin(max_retries=3):
    if not SMARTAPI_MPIN:
        return None
    if not SMARTAPI_TOTP_SECRET:
        print("WARN: No TOTP secret set; MPIN login requires TOTP. Skipping MPIN.")
        return None
    candidates = totp_candidates(SMARTAPI_TOTP_SECRET)
    attempt = 0
    while attempt < max_retries:
        for code in candidates:
            if not code:
                continue
            try:
                print(f"DEBUG: Trying MPIN login with totp={code} (attempt {attempt})")
                # Important: pass mpin as password param and totp as third param
                resp = s.generateSession(SMARTAPI_CLIENT_CODE, SMARTAPI_MPIN, code)
                print("Login response (MPIN):", resp)
                return resp
            except Exception as e:
                err = str(e)
                print("Exception during MPIN login:", err)
                # if rate-limit or access denied in response text, backoff more
                if "exceeding access rate" in err.lower() or "access denied" in err.lower():
                    backoff_sleep(attempt, base=2.0, cap=60.0)
                else:
                    # short sleep to avoid spam
                    time.sleep(1.0)
                # continue try other codes
        attempt += 1
        backoff_sleep(attempt)
    return None

# Password+TOTP fallback (only if server allows)
def try_login_password_totp():
    if not SMARTAPI_PASSWORD or not SMARTAPI_TOTP_SECRET:
        print("DEBUG: Password or TOTP secret missing; cannot attempt password+totp.")
        return None
    if not pyotp:
        print("WARN: pyotp missing; cannot generate TOTP")
        return None

    candidates = totp_candidates(SMARTAPI_TOTP_SECRET)
    for code in candidates:
        if not code:
            continue
        try:
            print(f"DEBUG: Trying password+totp with totp={code}")
            resp = s.generateSession(SMARTAPI_CLIENT_CODE, SMARTAPI_PASSWORD, code)
            print("Login response (pwd+totp):", resp)
            # server may explicitly disallow password login — check message
            if isinstance(resp, dict):
                msg = str(resp.get("message", "")).lower()
                if "loginbypassword is not allowed" in msg or "switch to login by mpin" in msg:
                    print("DEBUG: Server forbids password login.")
                    return resp
                if resp.get("status"):
                    return resp
            # small sleep between tries
            time.sleep(1.0)
        except Exception as e:
            err = str(e)
            print("Exception during pwd+totp attempt:", err)
            if "exceeding access rate" in err.lower() or "access denied" in err.lower():
                print("DEBUG: Rate-limited by server; backing off.")
                time.sleep(5.0)
            else:
                time.sleep(1.0)
    return None

def main():
    print("Starting login flow at", datetime.datetime.utcnow().isoformat())

    # 1) Try MPIN (mpin+totp)
    resp = try_login_mpin(max_retries=3)
    if resp and isinstance(resp, dict) and resp.get("status"):
        print("✅ MPIN login successful.")
        return

    # 2) Try password+totp fallback (server may disallow)
    resp2 = try_login_password_totp()
    if resp2 and isinstance(resp2, dict) and resp2.get("status"):
        print("✅ Password+TOTP login successful.")
        return

    print("❌ Login failed. MPIN resp:", resp, "pwd+totp resp:", resp2)
    sys.exit(1)

if __name__ == "__main__":
    main()
