# app/utils/api_key_auth.py
import os
from fastapi import Header, HTTPException, status

MAINTENANCE_CALLBACK_API_KEY = os.getenv("MAINTENANCE_CALLBACK_API_KEY")


def verify_maintenance_api_key(x_api_key: str = Header(...)):
    if x_api_key != MAINTENANCE_CALLBACK_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
        )