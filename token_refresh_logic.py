import os
import json
import base64
import requests
import time
from loguru import logger
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo 
import schedule 
import tzlocal  

# === Tip Jar ===
"https://www.paypal.com/paypalme/chancevandyke"

# === Timezone setup ===
try:
    # Attempt to auto-detect the system timezone
    LOCAL_TIMEZONE = tzlocal.get_localzone()  # returns a tzinfo object
    logger.info(f"🌍 Auto-detected system timezone: {LOCAL_TIMEZONE}")
except Exception as e:
    # Fallback timezone if detection fails
    LOCAL_TIMEZONE = ZoneInfo("America/Chicago")
    logger.warning(f"⚠️ Could not auto-detect timezone, defaulting to America/Chicago: {e}")

# === Configurable flag ===
AUTO_REFRESH_ENABLED = False  # Set to False to disable auto-refresh / True to update every 7 days

# === Load secrets ===
script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = "File path"

# Load existing secrets
with open(config_path) as f:
    config = json.load(f)

app_key = config["APP_KEY"]
app_secret = config["APP_SECRET"]

def should_refresh_refresh_token():
    last_refresh_update_str = config.get("LAST_REFRESH_TOKEN_UPDATE")
    now = datetime.now(tz=LOCAL_TIMEZONE)

    def parse_dt(dt_str):
        return datetime.strptime(dt_str, "%m/%d/%y %H:%M").replace(tzinfo=LOCAL_TIMEZONE)

    try:
        last_refresh_update = parse_dt(last_refresh_update_str) if last_refresh_update_str else None
    except Exception as e:
        logger.warning(f"⚠️ Could not parse refresh token timestamp: {e}")
        return True  # safer to refresh

    return not last_refresh_update or (now - last_refresh_update) >= timedelta(days=7)


def refresh_tokens(force_refresh_token=False):
    logger.info("🔁 Initializing token refresh...")

    refresh_token_value = config.get("REFRESH_TOKEN")
    if not refresh_token_value:
        logger.error("❌ No refresh token found in config.")
        return None

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_value,
    }

    headers = {
        "Authorization": f'Basic {base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()}',
        "Content-Type": "application/x-www-form-urlencoded",
    }

    response = requests.post(
        url="https://api.schwabapi.com/v1/oauth/token",
        headers=headers,
        data=payload,
    )

    if response.status_code != 200:
        logger.error(f"❌ Error refreshing token: {response.text}")
        return None

    token_data = response.json()
    logger.debug(token_data)

    now = datetime.now(tz=LOCAL_TIMEZONE)
    now_str = now.strftime("%m/%d/%y %H:%M")

    # === Access Token ===
    config["ACCESS_TOKEN"] = token_data.get("access_token")
    config["LAST_ACCESS_TOKEN_REFRESH"] = now_str
    logger.info("✅ Access token successfully refreshed.")

    # === Refresh Token Handling ===
    new_refresh_token = token_data.get("refresh_token")

    if new_refresh_token:
        if new_refresh_token != refresh_token_value:
            logger.info("🆕 New refresh token received and saved.")
            config["REFRESH_TOKEN"] = new_refresh_token
            config["LAST_REFRESH_TOKEN_UPDATE"] = now_str
            # Set expiry 7 days from now
            refresh_token_expiry = now + timedelta(days=7)
            config["REFRESH_TOKEN_EXPIRES_AT"] = refresh_token_expiry.strftime("%m/%d/%y %H:%M")
        else:
            logger.info("♻️ Refresh token reused — still valid.")
            if force_refresh_token:
                # If forced, still update the refresh timestamp and expiry
                config["LAST_REFRESH_TOKEN_UPDATE"] = now_str
                refresh_token_expiry = now + timedelta(days=7)
                config["REFRESH_TOKEN_EXPIRES_AT"] = refresh_token_expiry.strftime("%m/%d/%y %H:%M")
    else:
        logger.warning("❌ No refresh token returned by server — using existing one if still valid.")

    # === Save Config ===
    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)
        logger.info("💾 Updated tokens saved to app_secrets.json.")

    return token_data

if __name__ == "__main__":
    logger.info(f"🔁 Starting token logic. Auto-refresh is {'enabled' if AUTO_REFRESH_ENABLED else 'disabled'}.")

    if AUTO_REFRESH_ENABLED:
        logger.info("🕒 Auto-refresh enabled: refreshing access token every 29 minutes, refresh token if due.")

        def auto_refresh_job():
            refresh_token_due = should_refresh_refresh_token()
            if refresh_token_due:
                logger.info("🔄 Refresh token is older than 7 days, refreshing refresh token and access token.")
                refresh_tokens(force_refresh_token=True)
            else:
                logger.info("⏳ Refresh token still valid, refreshing access token only.")
                refresh_tokens(force_refresh_token=False)

        # Run once immediately
        auto_refresh_job()

        schedule.every(29).minutes.do(auto_refresh_job)

        while True:
            schedule.run_pending()
            time.sleep(10)

    else:
        # Manual run: refresh if refresh token older than 7 days
        if should_refresh_refresh_token():
            logger.info("📆 Refresh token older than 7 days — refreshing tokens.")
            refresh_tokens(force_refresh_token=True)
        else:
            logger.info("♻️ Refresh token still valid. No refresh needed.")
