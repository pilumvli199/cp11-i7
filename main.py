#!/usr/bin/env python3
# main.py - Indian Market Bot (SmartAPI + OpenAI + Telegram)
# Supports MPIN login (preferred) or Password+TOTP fallback.
# Fill values in .env (see .env.example).

import os, asyncio, json, time, traceback
from datetime import datetime, timedelta
from tempfile import NamedTemporaryFile

from dotenv import load_dotenv
load_dotenv()

import requests
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.dates import date2num

# optional libraries
try:
    import aiohttp
except Exception:
    print("Missing aiohttp. Install with pip install aiohttp"); raise
try:
    import pyotp
except Exception:
    print("Missing pyotp. Install with pip install pyotp"); raise
try:
    try:
        from SmartApi import SmartConnect
    except Exception:
        from smartapi import SmartConnect
except Exception:
    print("Missing SmartAPI library. Install smartapi-python and its deps"); raise
try:
    import openai
except Exception:
    openai = None

# ---------------- CONFIG ----------------
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

SMARTAPI_CLIENT_CODE = os.getenv('SMARTAPI_CLIENT_ID') or os.getenv('SMARTAPI_CLIENT_CODE')
SMARTAPI_API_KEY = os.getenv('SMARTAPI_API_KEY')
SMARTAPI_API_SECRET = os.getenv('SMARTAPI_API_SECRET')
SMARTAPI_MPIN = os.getenv('SMARTAPI_MPIN')
SMARTAPI_PASSWORD = os.getenv('SMARTAPI_PASSWORD')
SMARTAPI_TOTP_SECRET = os.getenv('SMARTAPI_TOTP_SECRET')

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_MODEL = os.getenv('OPENAI_MODEL','gpt-4o-mini')
if openai and OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

POLL_INTERVAL = int(os.getenv('POLL_INTERVAL',120))
SIGNAL_CONF_THRESHOLD = float(os.getenv('SIGNAL_CONF_THRESHOLD',70))

# minimal main - login check only
async def main():
    print("Starting minimal bot...")
    try:
        # attempt SmartAPI import/login
        try:
            s = SmartConnect(api_key=SMARTAPI_API_KEY)
        except Exception as e:
            print("SmartAPI import/connect error:", e)
            return
        if SMARTAPI_MPIN:
            try:
                resp = s.generateSession(SMARTAPI_CLIENT_CODE, SMARTAPI_MPIN, SMARTAPI_API_SECRET)
            except TypeError:
                resp = s.generateSession(SMARTAPI_CLIENT_CODE, SMARTAPI_MPIN)
        else:
            if not (SMARTAPI_PASSWORD and SMARTAPI_TOTP_SECRET):
                print("MPIN not set and password/totp missing. Exiting.")
                return
            totp = pyotp.TOTP(SMARTAPI_TOTP_SECRET).now()
            resp = s.generateSession(SMARTAPI_CLIENT_CODE, SMARTAPI_PASSWORD, totp)
        print("Login response:", resp)
    except Exception as e:
        print("Main exception:", e)

if __name__ == '__main__':
    asyncio.run(main())