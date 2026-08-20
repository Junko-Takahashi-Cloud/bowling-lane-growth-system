from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Staff
from app.utils.auth import SECRET_KEY, ALGORITHM

STAFF_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
staff_oauth2_scheme = HTTPBearer(auto_error=False)

# 実機生成した正当な60文字のbcryptハッシュ（存在しないIDへのアクセスでもbcrypt計算コストを揃え、
# タイミング攻撃によるID列挙を防止するためのダミー値）
DUMMY_PIN_HASH = "$2b$12$EBZ9DXV5Kex8Zna4fmWrrO.GlqVEIv/0HOR2O2vIe7e4ySMJe9/9C"


def hash_pin(pin_code: str) -> str:
    return pwd_context.hash(pin_code)


def verify_pin(plain_pin: str, pin_hash: str) -> bool:
    return pwd_context.verify(plain_pin, pin_hash)


def create_staff_access_token(staff_id: int, role: str, must_change_pin: bool = False) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=STAFF_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "staff_id": staff_id,
        "role": role,
        "type": "staff",
        "must_change_pin": must_change_pin,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def authenticate_staff_by_id_and_pin(db: Session, staff_id: int, pin_code: str) -> Optional[Staff]:
    staff = db.query(Staff).filter(Staff.staff_id == staff_id, Staff.is_active == True).first()
    now = datetime.now(timezone.utc)

    if not staff:
        # 存在しないID：ダミーハッシュで検証時間を揃え、ID列挙を防止
        verify_pin(pin_code, DUMMY_PIN_HASH)
        return None

    if staff.locked_until:
        locked_until_utc = (
            staff.locked_until if staff.locked_until.tzinfo else staff.locked_until.replace(tzinfo=timezone.utc)
        )
        if locked_until_utc > now:
            verify_pin(pin_code, DUMMY_PIN_HASH)
            return None
        else:
            staff.failed_attempts = 0
            staff.locked_until = None
            db.commit()

    if verify_pin(pin_code, staff.pin_hash):
        staff.failed_attempts = 0
        staff.locked_until = None
        db.commit()
        return staff
    else:
        staff.failed_attempts = (staff.failed_attempts or 0) + 1
        if staff.failed_attempts >= MAX_FAILED_ATTEMPTS:
            staff.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
        db.commit()
        return None


def get_current_staff(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(staff_oauth2_scheme),
    db: Session = Depends(get_db),
) -> Staff:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="スタッフ認証情報が無効です",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise credentials_exception

    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "staff":
            raise credentials_exception

        raw_staff_id = payload.get("staff_id")
        if raw_staff_id is None:
            raise credentials_exception

        staff_id = int(raw_staff_id)
        must_change_pin = payload.get("must_change_pin", False)
    except (JWTError, ValueError):
        raise credentials_exception

    staff = db.query(Staff).filter(Staff.staff_id == staff_id).first()
    if staff is None or not staff.is_active:
        raise credentials_exception

    if must_change_pin and not request.url.path.endswith("/api/v1/staff/me/pin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="初回PINの変更が必要です。PIN変更エンドポイント(PATCH /api/v1/staff/me/pin)で新しいPINを設定してください。",
        )

    return staff


def require_admin_staff(current_staff: Staff = Depends(get_current_staff)) -> Staff:
    if current_staff.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この操作には管理者(admin)権限が必要です",
        )
    return current_staff
