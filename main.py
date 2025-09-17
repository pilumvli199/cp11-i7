#!/usr/bin/env python3
# main.py - Robust SmartAPI login (copy-paste replace)
# Fill values in .env (see .env.example)

import os
import sys
import time
import datetime
import traceback

# debug: show which python is running and initial path
print("DEBUG: Python executable:", sys.executable)
print("DEBUG: initial sys.path[:8]:", sys.path[:8])

# Try to (optionally) install missing packages at runtime - convenience only
# Prefer preinstall via requirements.txt / Dockerfile for production
def _try_runtime_install():
    try:
        import importlib
        need = []
        checks = {
            "smartapi-python": ["smartapi"],
            "pyotp": ["pyotp"],
            "python-dotenv": ["dotenv"],
        }
        for pip_pkg, mods in checks.items():
            ok = False
            for m in mods:
                try:
                    importlib.import_module(m)
                    ok = True
                    break
                except Exception:
                    continue
            if not ok:
                need.append(pip_pkg)
        if not need:
            return True
        print("INFO: Runtime install required for:", need)
        import subprocess
        for pkg in need:
            print("INFO: Installing", pkg)
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", pkg])
        return True
    except Exception as e:
        print("WARN: Runtime install failed:", e)
        return False

# Attempt runtime install (harmless if already installed)
_try_runtime_install()

# Now import essentials
try:
    from dotenv import load_dotenv
    import pyotp
    from smartapi import SmartConnect
except Exception as e:
    print("❌ Could not import required modules. Details:")
    traceback.print_exc()
    # show pip freeze for debugging if possible
    try:
        import subprocess
        print("\n---- pip freeze ----")
        subprocess.call([sys.executable, "-m", "pip", "freeze"])
    except Exception:
        pass
    sys.exit(1)

# After successful imports, show sys.path again
print("DEBUG: sys.path after imports[:8]:", sys.path[:8])

# Load environment
load_dotenv()

# Env keys (match your .env)
SMARTAPI_API_KEY = os.getenv("SMARTAPI_API_KEY", "").strip()
SMARTAPI_CLIENT_CODE = os.getenv("SMARTAPI_CLIENT_CODE", "").strip()  # e.g. P482208
SMARTAPI_MPIN = os.getenv("SMARTAPI_MPIN", "").strip()               # optional
SMARTAPI_PASSWORD = os.getenv("SMARTAPI_PASSWORD", "").strip()       # fallback
SMARTAPI_TOTP_SECRET = os.getenv("SMARTAPI_TOTP_SECRET", "").strip() # base32 secret

# Basic sanity checks
if not SMARTAPI_CLIENT_CODE:
    print("❌ Missing SMARTAPI_CLIENT_CODE in .env. Set your client code (e.g. P482208).")
    sys.exit(1)

# SmartConnect init (robust)
try:
    try:
        s = SmartConnect(api_key=SMARTAPI_API_KEY)  # newer signature
    except TypeError:
        s = SmartConnect(SMARTAPI_API_KEY)  # fallback
except Exception:
    print("❌ SmartConnect init failed. Traceback:")
    traceback.print_exc()
    sys.exit(1)

def try_login_with_mpin():
    """Try MPIN login if MPIN provided. Return response or None."""
    if not SMARTAPI_MPIN:
        return None
    try:
        print("DEBUG: Trying MPIN login (clientcode, mpin)...")
        # Some SmartAPI variants may expect mpin + api_secret - adapt if needed
        try:
            resp = s.generateSession(SMARTAPI_CLIENT_CODE, SMARTAPI_MPIN, SMARTAPI_API_KEY)
        except TypeError:
            resp = s.generateSession(SMARTAPI_CLIENT_CODE, SMARTAPI_MPIN)
        print("Login response (MPIN):", resp)
        return resp
    except Exception as e:
        print("Exception during MPIN login:", e)
        traceback.print_exc()
        return None

def try_login_with_password_totp():
    """Try Password + TOTP (±30s)"""
    if not SMARTAPI_PASSWORD or not SMARTAPI_TOTP_SECRET:
        print("MPIN not set and password/totp missing. Cannot login.")
        return None

    # Validate totp secret looks like base32-ish
    def looks_like_base32(s):
        import re
        return bool(re.fullmatch(r"[A-Z2-7]+=*", s.upper()))

    print("DEBUG: TOTP secret looks like base32?:", looks_like_base32(SMARTAPI_TOTP_SECRET))
    totp_obj = pyotp.TOTP(SMARTAPI_TOTP_SECRET)
    print("DEBUG: Local UTC time:", datetime.datetime.utcnow().isoformat())
    print("DEBUG: Local epoch:", int(time.time()))
    current_code = totp_obj.now()
    print("DEBUG: Current TOTP (local):", current_code)

    epoch = int(time.time())
    candidates = []
    for offset in (-30, 0, 30):
        try:
            candidates.append((offset, totp_obj.at(epoch + offset)))
        except Exception as e:
            candidates.append((offset, None))

    print("DEBUG: TOTP candidates (offset,code):", candidates)

    for offset, code in candidates:
        if not code:
            continue
        code_str = str(code).zfill(6)
        try:
            print(f"DEBUG: Trying login with totp={code_str} (offset {offset}s)")
            resp = s.generateSession(SMARTAPI_CLIENT_CODE, SMARTAPI_PASSWORD, code_str)
            print("Login response (pwd+totp):", resp)
            if isinstance(resp, dict) and resp.get("status"):
                return resp
            # otherwise try next
        except Exception as e:
            print("Exception during password+totp login attempt:", e)
            traceback.print_exc()
            # continue trying others

    return None

def main():
    print("Starting bot: attempt login...")

    # 1) Try MPIN first (if provided)
    resp = try_login_with_mpin()
    if resp and isinstance(resp, dict) and resp.get("status"):
        print("✅ MPIN login successful.")
    else:
        # 2) Try password+totp fallback
        resp2 = try_login_with_password_totp()
        if resp2 and isinstance(resp2, dict) and resp2.get("status"):
            print("✅ Password+TOTP login successful.")
        else:
            print("❌ All login attempts failed. Response MPIN:", resp, "Response pwd+totp:", resp2 if 'resp2' in locals() else None)
            sys.exit(1)

    # After successful login, continue with your bot logic
    print("Bot logged in successfully. Continue with market data / subscriptions ...")
    # -------------------------
    # Place your further bot logic below
    # e.g., s.get_profile(), subscribe websocket, fetch data etc.
    # -------------------------

if __name__ == "__main__":
    main()
