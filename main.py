#!/usr/bin/env python3
# main.py - Robust SmartAPI login with proper TOTP usage and debug prints

import os
import time
import datetime
import sys
import traceback
from dotenv import load_dotenv
import pyotp

# -----------------------
# Load env
# -----------------------
load_dotenv()

SMARTAPI_API_KEY = os.getenv("SMARTAPI_API_KEY", "").strip()
SMARTAPI_CLIENT_ID = os.getenv("SMARTAPI_CLIENT_ID", "").strip()
SMARTAPI_CLIENT_PWD = os.getenv("SMARTAPI_CLIENT_PWD", "").strip()
SMARTAPI_TOTP_SECRET = os.getenv("SMARTAPI_TOTP_SECRET", "").strip()

# Quick sanity
if not SMARTAPI_API_KEY or not SMARTAPI_CLIENT_ID or not SMARTAPI_CLIENT_PWD:
    print("❌ Missing SmartAPI credentials (API_KEY/CLIENT_ID/CLIENT_PWD). Check your .env.")
    sys.exit(1)

if not SMARTAPI_TOTP_SECRET:
    print("❌ Missing SMARTAPI_TOTP_SECRET in .env. You must set the BASE32 TOTP secret from Angel/Authenticator app.")
    sys.exit(1)

# -----------------------
# Imports that may fail
# -----------------------
try:
    # Strictly use lowercase package name
    from smartapi import SmartConnect
except Exception as e:
    print("❌ Could not import smartapi. Have you installed requirements? (smartapi-python, twisted, autobahn...)")
    traceback.print_exc()
    raise

# Check twisted presence for clearer error if missing
try:
    import twisted  # noqa: F401
except ModuleNotFoundError:
    print("❌ 'twisted' not installed — required for smartapi websockets. Add twisted, autobahn, service-identity to requirements.txt")
    raise

# -----------------------
# Helper: validate base32-looking secret
# -----------------------
def looks_like_base32(s):
    import re
    return bool(re.fullmatch(r"[A-Z2-7]+=*", s.upper()))

print("DEBUG: SMARTAPI_CLIENT_ID (first 12 chars):", SMARTAPI_CLIENT_ID[:12])
print("DEBUG: SMARTAPI_API_KEY (first 12 chars):", SMARTAPI_API_KEY[:12])
print("DEBUG: SMARTAPI_TOTP_SECRET (first 12 chars):", SMARTAPI_TOTP_SECRET[:12])
print("DEBUG: TOTP secret looks like base32?:", looks_like_base32(SMARTAPI_TOTP_SECRET))

# -----------------------
# Create SmartConnect (robust)
# -----------------------
try:
    try:
        s = SmartConnect(api_key=SMARTAPI_API_KEY)
    except TypeError:
        # fallback if constructor signature is different
        s = SmartConnect(SMARTAPI_API_KEY)
except Exception:
    print("❌ SmartConnect init failed. Full traceback below:")
    traceback.print_exc()
    raise

# -----------------------
# Generate TOTP (and try ±1 window for clock drift)
# -----------------------
totp_obj = pyotp.TOTP(SMARTAPI_TOTP_SECRET)

# show local times for debugging
print("DEBUG: Local UTC time:", datetime.datetime.utcnow().isoformat())
print("DEBUG: Local epoch:", int(time.time()))

# current code
current_code = totp_obj.now()
print("DEBUG: Current TOTP (local):", current_code)   # should be 6 digits

# generate codes to try (current and ±1 step)
epoch = int(time.time())
codes_to_try = []
for offset in (-30, 0, 30):
    t = epoch + offset
    try:
        codes_to_try.append((offset, totp_obj.at(t)))
    except Exception as e:
        print("DEBUG: pyotp.at() error:", e)
        codes_to_try.append((offset, None))

print("DEBUG: Codes to try (offset seconds, code):", codes_to_try)

# -----------------------
# Clean & prepare clientcode/password values
# -----------------------
# Remove stray quotes or whitespace that may have crept in
clientcode_clean = SMARTAPI_CLIENT_ID.strip().strip('"').strip("'")
password_clean = SMARTAPI_CLIENT_PWD.strip().strip('"').strip("'")

print("DEBUG: clientcode_clean:", clientcode_clean)
# avoid printing password in logs in production; printing truncated for debug
print("DEBUG: password_clean (first 4 chars):", password_clean[:4] + ("***" if len(password_clean) > 4 else ""))

# -----------------------
# Try login with each totp candidate
# -----------------------
login_response = None
for offset_seconds, code in codes_to_try:
    if not code:
        continue
    # ensure code is a 6-digit string
    code_str = str(code).zfill(6)
    request_body = {
        "clientcode": clientcode_clean,
        "password": password_clean,
        "totp": code_str
    }
    print(f"DEBUG: Trying login with totp={code_str} (offset {offset_seconds}s). Request body:", request_body)
    try:
        resp = s.generateSession(clientcode_clean, password_clean, code_str)
        print("Login response:", resp)
        login_response = resp
        # check success
        if isinstance(resp, dict) and resp.get("status"):
            print("✅ Login successful.")
            break
        else:
            print("❌ Login failed for this code. Server message:", resp.get("message") if isinstance(resp, dict) else resp)
    except Exception as e:
        print("Exception during generateSession call:", e)
        traceback.print_exc()
        login_response = {"status": False, "message": str(e)}
        # continue trying other codes

if not login_response or not (isinstance(login_response, dict) and login_response.get("status")):
    print("❌ All login attempts failed. Last response:", login_response)
    # do not raise here if you want the bot to continue; exit to be explicit
    sys.exit(1)

# -----------------------
# Continue with bot logic...
# -----------------------
print("Bot ready — continue with market data / subscriptions ...")
# your further logic starts below this line
# --------------------------------------------------
