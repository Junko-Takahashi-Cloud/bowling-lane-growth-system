# app/services/maintenance_client.py
import os
import requests
from datetime import date

MAINTENANCE_API_URL = os.getenv("MAINTENANCE_API_URL")
MAINTENANCE_API_KEY = os.getenv("MAINTENANCE_API_KEY")


def request_gear_maintenance(gear_id: int, gear_name: str, maintenance_type: str = "clean") -> None:
    if not MAINTENANCE_API_URL:
        return
    try:
        requests.post(
            f"{MAINTENANCE_API_URL}/maintenance_log",
            json={
                "target_type": "member_gear",
                "target_id": gear_id,
                "maintenance_type": maintenance_type,
                "maintenance_category": "日常",
                "action_date": date.today().isoformat(),
                "note": f"会員依頼: {gear_name}",
            },
            headers={"X-API-Key": MAINTENANCE_API_KEY},
            timeout=5,
        )
    except requests.RequestException:
        pass