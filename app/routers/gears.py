from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Gear, User, Staff
from app.schemas import GearCreate, GearSelfCreate, GearOut
from app.utils.staff_auth import get_current_staff
from app.utils.user_auth import get_current_user

router = APIRouter(prefix="/api/v1/gears", tags=["gears"])


def _create_gear(db: Session, user_id: int, gear_type: str, name: str, weight_or_size) -> Gear:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会員が見つかりません")

    gear = Gear(
        user_id=user_id,
        gear_type=gear_type,
        name=name,
        weight_or_size=weight_or_size,
        total_games=0,
        status="active",
    )
    db.add(gear)
    db.commit()
    db.refresh(gear)
    return gear


@router.post("", response_model=GearOut, status_code=status.HTTP_201_CREATED)
def register_gear_self(
    payload: GearSelfCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """会員セルフ登録ルート。会員本人認証必須。対象は常にトークンの本人（他人へのなりすまし登録を防止）"""
    return _create_gear(db, current_user.id, payload.gear_type, payload.name, payload.weight_or_size)


@router.post("/by-staff", response_model=GearOut, status_code=status.HTTP_201_CREATED)
def register_gear_by_staff(
    payload: GearCreate,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    """フロントスタッフによる代理登録ルート"""
    return _create_gear(db, payload.user_id, payload.gear_type, payload.name, payload.weight_or_size)


@router.get("/user/{user_id}", response_model=list[GearOut])
def list_gears_for_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    """スタッフによる閲覧（フロント業務用）"""
    return db.query(Gear).filter(Gear.user_id == user_id).all()


@router.get("/me", response_model=list[GearOut])
def list_my_gears(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """会員本人が自分のギア一覧を閲覧する"""
    return db.query(Gear).filter(Gear.user_id == current_user.id).all()
