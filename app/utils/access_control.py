from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Staff, User
from app.utils.auth import SECRET_KEY, ALGORITHM

_bearer_scheme = HTTPBearer(auto_error=False)


def require_staff_or_self(path_param_name: str = "user_id"):
    """パスパラメータ(既定でuser_id)に対して、
    - スタッフのトークンなら誰でも許可
    - 会員のトークンなら本人(パスのuser_idと一致)のみ許可
    という認可を行うDependencyを生成する。
    デフォルト引数はデコレータ評価時ではなくリクエスト実行時に解決する必要があるため、
    対象のuser_idはrequest.path_paramsから取得する（他の引数へのクロージャ参照は使わない）。"""

    def _checker(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
        db: Session = Depends(get_db),
    ):
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="認証情報が無効です",
            headers={"WWW-Authenticate": "Bearer"},
        )
        if credentials is None:
            raise credentials_exception

        target_user_id = int(request.path_params[path_param_name])

        try:
            payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        except JWTError:
            raise credentials_exception

        token_type = payload.get("type")

        if token_type == "staff":
            staff_id = payload.get("staff_id")
            if staff_id is None:
                raise credentials_exception
            staff = db.query(Staff).filter(Staff.staff_id == int(staff_id)).first()
            if staff is None or not staff.is_active:
                raise credentials_exception
            if payload.get("must_change_pin") and not request.url.path.endswith("/api/v1/staff/me/pin"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="初回PINの変更が必要です。",
                )
            return  # スタッフは誰でもOK

        if token_type == "member":
            raw_user_id = payload.get("user_id")
            if raw_user_id is None:
                raise credentials_exception
            if int(raw_user_id) != target_user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="他の会員のデータにはアクセスできません",
                )
            user = db.query(User).filter(User.id == int(raw_user_id)).first()
            if user is None:
                raise credentials_exception
            return  # 本人はOK

        raise credentials_exception

    return _checker
