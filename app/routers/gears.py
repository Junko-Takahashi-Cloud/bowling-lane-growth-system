from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Gear, User, Staff
from app.schemas import (
    GearCreate,
    GearSelfCreate,
    GearOut,
    MaintenanceReminderOut,
    MaintenanceReminderActionOut,
)
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

# ①オイル抜きリマインド：ギアのメンテナンス状況を返す
@router.get("/{gear_id}/reminder", response_model=MaintenanceReminderOut)
def get_maintenance_reminder(
    gear_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    gear = db.query(Gear).filter(Gear.id == gear_id).first()
    if not gear or gear.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="ギアが見つかりません")

    games_since = gear.games_since_maintenance

    if gear.maintenance_reminder_disabled:
        status = "disabled"
        message = "リマインダーは無効化されています"
        visible = False
    elif gear.maintenance_reminder_snoozed_stage is not None:
        status = "snoozed"
        message = "リマインダーはスヌーズ中です"
        visible = False
    elif games_since >= 30:
        status = "alert"
        message = "オイル抜きを推奨します"
        visible = True
    else:
        status = "normal"
        message = None
        visible = False

    return MaintenanceReminderOut(
        gear_id=gear.id,
        gear_name=gear.name,
        games_since_maintenance=games_since,
        reminder_status=status,
        reminder_message=message,
        reminder_visible=visible,
        reminder_disabled=gear.maintenance_reminder_disabled,
        snoozed_stage=gear.maintenance_reminder_snoozed_stage,
    )


# ①オイル抜きリマインド：無効化・スヌーズ操作
@router.post("/{gear_id}/reminder/action", response_model=MaintenanceReminderActionOut)
def update_maintenance_reminder(
    gear_id: int,
    action: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    gear = db.query(Gear).filter(Gear.id == gear_id).first()
    if not gear or gear.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="ギアが見つかりません")

    if action == "disable":
        gear.maintenance_reminder_disabled = True
        message = "リマインダーを無効化しました"
    elif action == "snooze":
        gear.maintenance_reminder_snoozed_stage = 1
        message = "リマインダーをスヌーズしました"
    elif action == "reset":
        gear.maintenance_reminder_disabled = False
        gear.maintenance_reminder_snoozed_stage = None
        message = "リマインダーをリセットしました"
    else:
        raise HTTPException(status_code=400, detail="不正なアクションです")

    db.commit()
    db.refresh(gear)

    return MaintenanceReminderActionOut(
        gear_id=gear.id,
        reminder_disabled=gear.maintenance_reminder_disabled,
        snoozed_stage=gear.maintenance_reminder_snoozed_stage,
        message=message,
    )
