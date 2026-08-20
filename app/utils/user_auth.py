from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.utils.auth import SECRET_KEY, ALGORITHM
from app.utils.staff_auth import hash_pin, verify_pin, DUMMY_PIN_HASH

MEMBER_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 会員は1週間有効（スタッフより長め）
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

member_oauth2_scheme = HTTPBearer(auto_error=False)


def create_user_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=MEMBER_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"user_id": user_id, "type": "member", "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _find_user_by_identifier(db: Session, identifier: str) -> Optional[User]:
    """会員コード または 電話番号のどちらでも本人を特定できるようにする"""
    return (
        db.query(User)
        .filter((User.member_code == identifier) | (User.phone_number == identifier))
        .first()
    )


def authenticate_user_by_identifier_and_pin(db: Session, identifier: str, pin_code: str) -> Optional[User]:
    user = _find_user_by_identifier(db, identifier)
    now = datetime.now(timezone.utc)

    if not user or not user.pin_hash:
        # 存在しない・PIN未設定の場合もダミーハッシュで検証時間を揃え、ID列挙を防止
        verify_pin(pin_code, DUMMY_PIN_HASH)
        return None

    if user.locked_until:
        locked_until_utc = (
            user.locked_until if user.locked_until.tzinfo else user.locked_until.replace(tzinfo=timezone.utc)
        )
        if locked_until_utc > now:
            verify_pin(pin_code, DUMMY_PIN_HASH)
            return None
        else:
            user.failed_attempts = 0
            user.locked_until = None
            db.commit()

    if verify_pin(pin_code, user.pin_hash):
        user.failed_attempts = 0
        user.locked_until = None
        db.commit()
        return user
    else:
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
        db.commit()
        return None


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(member_oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="会員認証情報が無効です",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise credentials_exception

    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "member":
            raise credentials_exception
        raw_user_id = payload.get("user_id")
        if raw_user_id is None:
            raise credentials_exception
        user_id = int(raw_user_id)
    except (JWTError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user


def try_get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(member_oauth2_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """スタッフ/会員どちらのトークンも受け付けたいエンドポイント用。
    会員トークンとして解釈できなければNoneを返す（例外を出さない）。"""
    if credentials is None:
        return None
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "member":
            return None
        raw_user_id = payload.get("user_id")
        if raw_user_id is None:
            return None
        user_id = int(raw_user_id)
    except (JWTError, ValueError):
        return None
    return db.query(User).filter(User.id == user_id).first()
