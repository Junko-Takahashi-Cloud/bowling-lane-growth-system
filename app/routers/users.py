from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Staff
from app.schemas import UserCreate, UserOut, UserLogin, UserToken, UserSetInitialPin, UserPinUpdate
from app.utils.staff_auth import get_current_staff, hash_pin, verify_pin
from app.utils.user_auth import (
    authenticate_user_by_identifier_and_pin,
    create_user_access_token,
    get_current_user,
)

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    """会員新規登録（フロント受付での登録を想定し、スタッフ認証必須）"""
    existing = db.query(User).filter(User.member_code == payload.member_code).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"会員コード '{payload.member_code}' は既に登録されています",
        )
    existing_phone = db.query(User).filter(User.phone_number == payload.phone_number).first()
    if existing_phone:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"電話番号 '{payload.phone_number}' は既に登録されています",
        )

    user = User(
        member_code=payload.member_code,
        name=payload.name,
        phone_number=payload.phone_number,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    return db.query(User).all()


@router.get("/me", response_model=UserOut)
def get_my_profile(current_user: User = Depends(get_current_user)):
    """会員本人のプロフィール取得。
    ルーティング順の注意: FastAPIはパスを登録順に評価するため、
    '/me' は '/{user_id}' より前に定義しないと、'me' がuser_idとして
    解釈されてしまい int変換エラー(422)になる。"""
    return current_user


@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会員が見つかりません")
    return user


@router.post("/set-initial-pin", response_model=UserToken)
def set_initial_pin(payload: UserSetInitialPin, db: Session = Depends(get_db)):
    """会員カードのコード＋登録済み電話番号で本人確認し、初回PINを設定する。
    PINが既に設定済みの場合は、本人確認手段としては使えない（上書き防止のため拒否）。"""
    user = (
        db.query(User)
        .filter(User.member_code == payload.member_code, User.phone_number == payload.phone_number)
        .first()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="会員コードまたは電話番号が正しくありません",
        )
    if user.pin_hash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PINは既に設定済みです。PINをお忘れの場合はスタッフにお問い合わせください。",
        )

    user.pin_hash = hash_pin(payload.pin_code)
    db.commit()
    db.refresh(user)

    token = create_user_access_token(user.id)
    return UserToken(access_token=token)


@router.post("/login", response_model=UserToken)
def user_login(payload: UserLogin, db: Session = Depends(get_db)):
    """会員コードまたは電話番号のどちらでもログイン可能"""
    user = authenticate_user_by_identifier_and_pin(db, payload.identifier, payload.pin_code)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="会員コード(または電話番号)、またはPINが正しくありません",
        )
    token = create_user_access_token(user.id)
    return UserToken(access_token=token)


@router.patch("/me/pin", response_model=UserToken)
def update_own_pin(
    payload: UserPinUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.pin_hash or not verify_pin(payload.current_pin, current_user.pin_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="現在のPINが正しくありません")

    current_user.pin_hash = hash_pin(payload.new_pin)
    db.commit()
    db.refresh(current_user)

    token = create_user_access_token(current_user.id)
    return UserToken(access_token=token)
