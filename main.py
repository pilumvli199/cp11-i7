#!/usr/bin/env python3
# main.py - Robust SmartAPI login (replace your current main.py with this)

import os
import sys
import time
import datetime
import traceback

# Debug: show interpreter and initial sys.path
print("DEBUG: Python executable:", sys.executable)
print("DEBUG: initial sys.path[:8]:", sys.path[:8])

# Optional convenience: try minimal runtime installs for missing essentials.
# (Prefer preinstall via requirements.txt/Dockerfile in production)
def runtime_ensure(packages_map):
    """packages_map: {pip_name: [module_names_to_try_import]}"""
    import importlib, subprocess
    to_install = []
    for pip_pkg, mods in packages_map.items():
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
            print("INFO: pip installing", pkg)
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", pkg])
        return True
    except Exception as e:
        print("WARN: runtime pip install failed:", e)
        traceback.print_exc()
        return False

# Ensure dotenv, pyotp and smartapi basics exist (convenience)
runtime_ensure({
    "python-dotenv": ["dotenv"],
    "pyotp": ["pyotp"],
    "smartapi-python": ["smartapi"],
})

# Now do imports (after attempted install)
try:
    from dotenv import load_dotenv
    import pyotp
    from smartapi import SmartConnect
except Exception as e:
    print("❌ Could not import required modules. Details:")
    traceback.print_exc()
    # Show pip freeze to help debug in logs
    try:
        import subprocess
        print("\n---- pip freeze ----")
        subprocess.call([sys.executable, "-m", "pip", "freeze"])
    except Exception:
        pass
    sys.exit(1)

# Check twisted presence for websocket support (clear message if missing)
try:
    import twisted  # noqa: F401
except Exception:
    print("WARN: 'twisted' not importable. If you need SmartAPI websockets, install twisted/autobahn/service-identity.")
    # Not exiting here — depending on your usage you may still use REST APIs.

# Show sys.path after imports
print("DEBUG: sys.path after imports[:8]:", sys.path[:8])

# Load env vars
load_dotenv()

SMARTAPI_API_KEY = os.getenv("SMARTAPI_API_KEY", "").strip()
SMARTAPI_CLIENT_CODE = os.getenv("SMARTAPI_CLIENT_CODE", "").strip()  # e.g. P482208
SMARTAPI_MPIN = os.getenv("SMARTAPI_MPIN", "").strip()               # optional
SMARTAPI_PASSWORD = os.getenv("SMARTAPI_PASSWORD", "").strip()       # fallback
SMARTAPI_TOTP_SECRET = os.getenv("SMARTAPI_TOTP_SECRET", "").strip() # base32 secret

# Basic sanity
if not SMARTAPI_CLIENT_CODE:
    print("❌ Missing SMARTAPI_CLIENT_CODE in .env. Set your client code (e.g. P482208).")
    sys.exit(1)

# Helper: validate base32-looking TOTP secret
def looks_like_base32(s):
    import re
    return bool(re.fullmatch(r"[A-Z2-7]+=*", s.upper())) if s else False

# SmartConnect init (robust)
try:
    try:
        s = SmartConnect(api_key=SMARTAPI_API_KEY)
    except TypeError:
        s = SmartConnect(SMARTAPI_API_KEY)
except Exception:
    print("❌ SmartConnect init failed. Traceback:")
    traceback.print_exc()
    sys.exit(1)

def try_login_mpin():
    """Try MPIN login if provided. Return response or None."""
    if not SMARTAPI_MPIN:
        return None
    try:
        print("DEBUG: Attempting MPIN login...")
        try:
            resp = s.generateSession(SMARTAPI_CLIENT_CODE, SMARTAPI_MPIN, SMARTAPI_API_KEY)
        except TypeError:
            resp = s.generateSession(SMARTAPI_CLIENT_CODE, SMARTAPI_MPIN)
        print("Login response (MPIN):", resp)
        return resp
    except Exception:
        print("Exception during MPIN login:")
        traceback.print_exc()
        return None

def try_login_password_totp():
    """Try Password + TOTP (±30s window)."""
    if not SMARTAPI_PASSWORD or not SMARTAPI_TOTP_SECRET:
        print("DEBUG: Password or TOTP secret missing; cannot attempt password+totp.")
        return None

    print("DEBUG: TOTP secret looks like base32?:", looks_like_base32(SMARTAPI_TOTP_SECRET))
    totp_obj = pyotp.TOTP(SMARTAPI_TOTP_SECRET)

    print("DEBUG: Local UTC time:", datetime.datetime.utcnow().isoformat())
    print("DEBUG: Local epoch:", int(time.time()))
    print("DEBUG: Current TOTP (local):", totp_obj.now())

    epoch = int(time.time())
    candidates = []
    for offset in (-30, 0, 30):
        try:
            candidates.append((offset, totp_obj.at(epoch + offset)))
        except Exception as e:
            print("WARN: pyotp.at() error for offset", offset, e)
            candidates.append((offset, None))

    print("DEBUG: TOTP candidates:", candidates)

    # cleanse clientcode/password from stray quotes
    clientcode_clean = SMARTAPI_CLIENT_CODE.strip().strip('"').strip("'")
    password_clean = SMARTAPI_PASSWORD.strip().strip('"').strip("'")

    for offset, code in candidates:
        if not code:
            continue
        code_str = str(code).zfill(6)
        try:
            print(f"DEBUG: Trying login with totp={code_str} (offset {offset}s)")
            resp = s.generateSession(clientcode_clean, password_clean, code_str)
            print("Login response (pwd+totp):", resp)
            if isinstance(resp, dict) and resp.get("status"):
                return resp
            # else continue trying
        except Exception:
            print("Exception during password+TOTP attempt:")
            traceback.print_exc()
            # continue to next candidate
    return None

def main():
    print("Starting bot — attempting login...")

    # 1) Try MPIN first (if exists)
    resp = try_login_mpin()
    if resp and isinstance(resp, dict) and resp.get("status"):
        print("✅ MPIN login successful.")
        logged_in = True
    else:
        # 2) Try password + totp fallback
        resp2 = try_login_password_totp()
        if resp2 and isinstance(resp2, dict) and resp2.get("status"):
            print("✅ Password+TOTP login successful.")
            logged_in = True
        else:
            print("❌ All login attempts failed. MPIN response:", resp, "pwd+totp response:", resp2 if 'resp2' in locals() else None)
            logged_in = False

    if not logged_in:
        # for debugging, exit early
        sys.exit(1)

    # After successful login continue bot logic
    print("Bot logged in. Continue with market data subscriptions / logic here.")
    # ---------- Put your bot logic below ----------
    # e.g. s.get_profile(), s.get_margin(), subscribe to websocket, etc.
    # ------------------------------------------------

if __name__ == "__main__":
    main()
