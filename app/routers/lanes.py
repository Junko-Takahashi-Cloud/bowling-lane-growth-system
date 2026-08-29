from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import LaneSettings, Lane, Staff
from app.schemas import LaneSettingsOut, LaneSettingsUpdate, LaneOut, LaneStatusUpdate, LanePurposeUpdate
from app.utils.staff_auth import get_current_staff, require_admin_staff

router = APIRouter(prefix="/api/v1/lanes", tags=["lanes"])


def _get_or_create_settings(db: Session) -> LaneSettings:
    settings = db.query(LaneSettings).first()
    if settings is None:
        settings = LaneSettings(total_lanes=4)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def _sync_lanes_to_total(db: Session, total_lanes: int) -> None:
    """total_lanesの範囲に足りないLaneレコードを追加生成する。
    既存のLaneは削除しない(故障記録やアサイン履歴を保持するため)。
    範囲外(total_lanesを超える番号)のLaneも自動削除はしない
    (誤って減らした場合にデータが消えないようにするための安全策)。"""
    existing_numbers = {lane.lane_number for lane in db.query(Lane).all()}
    for n in range(1, total_lanes + 1):
        if n not in existing_numbers:
            db.add(Lane(lane_number=n, status="available", purpose="general"))
    db.commit()


@router.get("/settings", response_model=LaneSettingsOut)
def get_lane_settings(
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    return _get_or_create_settings(db)


@router.patch("/settings", response_model=LaneSettingsOut)
def update_lane_settings(
    payload: LaneSettingsUpdate,
    db: Session = Depends(get_db),
    admin_staff: Staff = Depends(require_admin_staff),
):
    """総レーン数を変更する（例: 4→6への増設）。admin権限必須。
    変更後、不足しているレーン番号のLaneレコードを自動生成する。"""
    if payload.total_lanes < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="total_lanesは1以上である必要があります")

    settings = _get_or_create_settings(db)
    settings.total_lanes = payload.total_lanes
    db.commit()
    db.refresh(settings)

    _sync_lanes_to_total(db, payload.total_lanes)
    return settings


@router.get("", response_model=list[LaneOut])
def list_lanes(
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    settings = _get_or_create_settings(db)
    _sync_lanes_to_total(db, settings.total_lanes)
    return db.query(Lane).order_by(Lane.lane_number).all()


@router.patch("/{lane_number}/status", response_model=LaneOut)
def update_lane_status(
    lane_number: int,
    payload: LaneStatusUpdate,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    """故障・メンテナンス等によるレーンの使用可否を変更する。"""
    if payload.status not in ("available", "maintenance", "broken"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="statusは available/maintenance/broken のいずれかである必要があります",
        )
    lane = db.query(Lane).filter(Lane.lane_number == lane_number).first()
    if not lane:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="レーンが見つかりません")
    lane.status = payload.status
    db.commit()
    db.refresh(lane)
    return lane


@router.patch("/{lane_number}/purpose", response_model=LaneOut)
def update_lane_purpose(
    lane_number: int,
    payload: LanePurposeUpdate,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    """教室用・一般利用・競技者用などの用途を変更する。"""
    if payload.purpose not in ("general", "class", "competitor"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="purposeは general/class/competitor のいずれかである必要があります",
        )
    lane = db.query(Lane).filter(Lane.lane_number == lane_number).first()
    if not lane:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="レーンが見つかりません")
    lane.purpose = payload.purpose
    db.commit()
    db.refresh(lane)
    return lane
