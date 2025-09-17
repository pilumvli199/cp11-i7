#!/usr/bin/env python3
"""
main.py - Attempts to auto-install required packages if missing,
then runs SmartAPI login with proper TOTP handling.

WARNING: Runtime pip install is a convenience for debugging; prefer
preinstalling dependencies via requirements.txt or Dockerfile in production.
"""

import os
import sys
import time
import datetime
import traceback
from dotenv import load_dotenv

# ------------------------
# Try to ensure required packages are present at runtime
# ------------------------
REQUIRED_PIP_PACKAGES = [
    "smartapi-python>=1.4.9",
    "twisted==22.10.0",
    "autobahn==23.6.2",
    "service-identity==21.1.0",
    "pyotp>=2.9.0",
    "python-dotenv>=1.0.1"
]

def try_runtime_install(packages):
    """Try to pip install packages at runtime if missing."""
    import importlib
    missing = []
    # quick map: pip package -> import name(s) to check
    check_map = {
        "smartapi-python": ["smartapi"],
        "twisted": ["twisted"],
        "autobahn": ["autobahn"],
        "service-identity": ["service_identity", "service_identity"],
        "pyotp": ["pyotp"],
        "python-dotenv": ["dotenv"]
    }
    for pkg in packages:
        # normalize the pip name before checking map
        base = pkg.split("==")[0].split(">=")[0]
        imports = check_map.get(base, [base.replace("-", "_")])
        ok = False
        for mod in imports:
            try:
                importlib.import_module(mod)
                ok = True
                break
            except Exception:
                continue
        if not ok:
            missing.append(pkg)
    if not missing:
        return True

    print("INFO: Missing packages detected, attempting runtime pip install:", missing)
    try:
        import subprocess
        for m in missing:
            print("INFO: Installing", m)
            subprocess.check_call([sys.executable, "-m", "pip", "install", m])
        return True
    except Exception as e:
        print("ERROR: Runtime pip install failed:", e)
        traceback.print_exc()
        return False

# Attempt runtime install (safe to call)
try_runtime_install(REQUIRED_PIP_PACKAGES)

# ------------------------
# Now import rest (after attempted install)
# ------------------------
try:
    import pyotp
    from smartapi import SmartConnect
except Exception as e:
    print("❌ Could not import required modules even after attempting install. Details:")
    traceback.print_exc()
    # Print pip freeze for debugging (helpful in platform logs)
    try:
        import subprocess
        print("---- pip freeze ----")
        subprocess.call([sys.executable, "-m", "pip", "freeze"])
    except Exception:
        pass
    sys.exit(1)

# check twisted specifically
try:
    import twisted  # noqa: F401
except Exception as e:
    print("❌ 'twisted' missing or failed to import. Ensure twisted/autobahn/service-identity installed.")
    traceback.print_exc()
    sys.exit(1)

# ------------------------
# Load .env
# ------------------------
load_dotenv()

SMARTAPI_API_KEY = os.getenv("SMARTAPI_API_KEY", "").strip()
SMARTAPI_CLIENT_ID = os.getenv("SMARTAPI_CLIENT_ID", "").strip()
SMARTAPI_CLIENT_PWD = os.getenv("SMARTAPI_CLIENT_PWD", "").strip()
SMARTAPI_TOTP_SECRET = os.getenv("SMARTAPI_TOTP_SECRET", "").strip()

if not SMARTAPI_API_KEY or not SMARTAPI_CLIENT_ID or not SMARTAPI_CLIENT_PWD:
    print("❌ Missing SmartAPI credentials (API_KEY/CLIENT_ID/CLIENT_PWD). Check your .env.")
    sys.exit(1)

if not SMARTAPI_TOTP_SECRET:
    print("❌ Missing SMARTAPI_TOTP_SECRET in .env. You must set the BASE32 TOTP secret from Angel/Authenticator app.")
    sys.exit(1)

# small helper
def looks_like_base32(s):
    import re
    return bool(re.fullmatch(r"[A-Z2-7]+=*", s.upper()))

print("DEBUG: client_id:", SMARTAPI_CLIENT_ID[:16])
print("DEBUG: totp looks base32?:", looks_like_base32(SMARTAPI_TOTP_SECRET))

# ------------------------
# SmartConnect init (robust)
# ------------------------
try:
    try:
        s = SmartConnect(api_key=SMARTAPI_API_KEY)
    except TypeError:
        s = SmartConnect(SMARTAPI_API_KEY)
except Exception:
    print("❌ SmartConnect init failed. Traceback:")
    traceback.print_exc()
    sys.exit(1)

# ------------------------
# TOTP generation & login attempts (±1 window)
# ------------------------
totp_obj = pyotp.TOTP(SMARTAPI_TOTP_SECRET)

print("DEBUG: Local UTC time:", datetime.datetime.utcnow().isoformat())
print("DEBUG: Local epoch:", int(time.time()))
current_code = totp_obj.now()
print("DEBUG: Current TOTP (local):", current_code)

epoch = int(time.time())
codes_to_try = []
for offset in (-30, 0, 30):
    try:
        codes_to_try.append((offset, totp_obj.at(epoch + offset)))
    except Exception as e:
        codes_to_try.append((offset, None))
print("DEBUG: Codes to try:", codes_to_try)

clientcode_clean = SMARTAPI_CLIENT_ID.strip().strip('"').strip("'")
password_clean = SMARTAPI_CLIENT_PWD.strip().strip('"').strip("'")

login_response = None
for offset_seconds, code in codes_to_try:
    if not code:
        continue
    code_str = str(code).zfill(6)
    print(f"DEBUG: Trying login with totp={code_str} (offset {offset_seconds}s)")
    try:
        resp = s.generateSession(clientcode_clean, password_clean, code_str)
        print("Login response:", resp)
        login_response = resp
        if isinstance(resp, dict) and resp.get("status"):
            print("✅ Login successful.")
            break
        else:
            print("❌ Login failed for this code. Server message:", resp.get("message") if isinstance(resp, dict) else resp)
    except Exception as e:
        print("Exception during generateSession call:", e)
        traceback.print_exc()
        login_response = {"status": False, "message": str(e)}

if not login_response or not (isinstance(login_response, dict) and login_response.get("status")):
    print("❌ All login attempts failed. Last response:", login_response)
    sys.exit(1)

print("Bot ready — continue with your bot logic here.")
# --------- your further bot logic below ----------
