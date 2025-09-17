#!/usr/bin/env python3
# main.py - Robust SmartAPI login (replace your current main.py with this)

import os
import sys
import time
import datetime
import traceback
import importlib

# Debug: interpreter + path
print("DEBUG: Python executable:", sys.executable)
print("DEBUG: initial sys.path[:8]:", sys.path[:8])

# Small helper: optionally attempt runtime install for essentials (convenience only)
def runtime_ensure(packages_map):
    import subprocess
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

# Ensure minimal libs (optional)
runtime_ensure({
    "python-dotenv": ["dotenv"],
    "pyotp": ["pyotp"],
    "smartapi-python": ["SmartApi", "smartapi"],  # try both package names
})

# Inspect site-packages for smart* candidates (helpful to debug weird installs)
def inspect_site_packages():
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
            continue
    print("DEBUG: Found candidates (first 200):")
    for c in candidates[:200]:
        print("  ", c)
    if not candidates:
        print("DEBUG: No smart* candidates found in sys.path entries scanned.")
    return candidates

candidates = inspect_site_packages()

# Try flexible imports — support both 'smartapi' (pypi smartapi-python) and legacy 'SmartApi' package dir
SmartConnect = None
import_errors = {}

possible_names = ["smartapi", "SmartApi", "smartapi_python", "smart_api"]

for name in possible_names:
    try:
        mod = importlib.import_module(name)
        print(f"DEBUG: Successful import as '{name}' -> {getattr(mod,'__file__', None)}")
        if hasattr(mod, "SmartConnect"):
            SmartConnect = getattr(mod, "SmartConnect")
            print(f"DEBUG: Found SmartConnect in module '{name}'.")
            break
        import_errors[name] = "imported_but_no_SmartConnect"
    except Exception as e:
        import_errors[name] = f"{type(e).__name__}: {e}"

# Try import from discovered candidate dirs (if above failed)
if SmartConnect is None and candidates:
    for path in candidates:
        base = os.path.basename(path)
        modname = os.path.splitext(base)[0]
        parent = os.path.dirname(path)
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

print("DEBUG: import_errors summary (partial):")
for k, v in list(import_errors.items())[:50]:
    print("  ", k, "->", v)

if SmartConnect is None:
    print("❌ Could not locate SmartConnect via tried imports. Final sys.path[:6]:", sys.path[:6])
    try:
        import subprocess
        print("\n---- pip freeze ----")
        subprocess.call([sys.executable, "-m", "pip", "freeze"])
    except Exception:
        pass
    sys.exit(1)

print("✅ SmartConnect resolved:", SmartConnect)

# Now import dotenv and pyotp (they should be available)
try:
    from dotenv import load_dotenv
except Exception:
    print("WARN: python-dotenv not importable; continuing (will use environment directly).")

try:
    import pyotp
except Exception:
    print("WARN: pyotp not importable; TOTP generation will fail if used.")

# Load env vars
try:
    load_dotenv()
except Exception:
    pass

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
    print("❌ Missing SMARTAPI_CLIENT_CODE. Set the env var and redeploy.")
    sys.exit(1)

# Initialize SmartConnect instance (robust)
try:
    try:
        s = SmartConnect(api_key=SMARTAPI_API_KEY)
    except TypeError:
        s = SmartConnect(SMARTAPI_API_KEY)
except Exception:
    print("❌ SmartConnect init failed. Traceback:")
    traceback.print_exc()
    sys.exit(1)

# Login helpers
def try_login_mpin():
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
        traceback.print_exc()
        return None

def try_login_password_totp():
    if not SMARTAPI_PASSWORD or not SMARTAPI_TOTP_SECRET:
        print("DEBUG: Password or TOTP secret missing; cannot attempt password+totp.")
        return None
    try:
        totp_obj = pyotp.TOTP(SMARTAPI_TOTP_SECRET)
    except Exception as e:
        print("DEBUG: pyotp init error:", e)
        return None

    print("DEBUG: Local UTC time:", datetime.datetime.utcnow().isoformat())
    print("DEBUG: Local epoch:", int(time.time()))
    print("DEBUG: Current TOTP (local):", totp_obj.now())

    epoch = int(time.time())
    for offset in (-30, 0, 30):
        try:
            code = totp_obj.at(epoch + offset)
        except Exception:
            code = None
        if not code:
            continue
        code_str = str(code).zfill(6)
        try:
            print(f"DEBUG: Trying login with totp={code_str} (offset {offset}s)")
            resp = s.generateSession(SMARTAPI_CLIENT_CODE, SMARTAPI_PASSWORD, code_str)
            print("Login response (pwd+totp):", resp)
            if isinstance(resp, dict) and resp.get("status"):
                return resp
        except Exception:
            traceback.print_exc()
    return None

def main():
    print("Starting login attempts...")
    resp = try_login_mpin()
    if resp and isinstance(resp, dict) and resp.get("status"):
        print("✅ MPIN login successful.")
        return
    resp2 = try_login_password_totp()
    if resp2 and isinstance(resp2, dict) and resp2.get("status"):
        print("✅ Password+TOTP login successful.")
        return
    print("❌ Login failed. See above logs for exact server response.")
    sys.exit(1)

if __name__ == "__main__":
    main()
