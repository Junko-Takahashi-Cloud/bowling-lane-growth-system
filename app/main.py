import os
import secrets
import string
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, Form, HTTPException, status
from sqlalchemy.orm import Session

from app.database import Base, engine, SessionLocal, get_db
from app.models import Staff, User, BowlingSession, SessionPlayer, Gear, MaintenanceLog, LaneSettings, Lane
from app.utils.staff_auth import hash_pin, get_current_staff
from app.routers import staff, users, gears, sessions, scores, dashboard, class_completion, lanes, badges

logger = logging.getLogger("uvicorn")

Base.metadata.create_all(bind=engine)


def seed_initial_admin(db: Session):
    """管理者(admin)が1人もいない場合、数字専用キーパッド対応の8桁ランダムPINで初期管理者を生成"""
    has_admin = db.query(Staff).filter(Staff.role == "admin").first()
    if not has_admin:
        initial_pin = "".join(secrets.choice(string.digits) for _ in range(8))
        default_admin = Staff(
            name="初期管理者",
            pin_hash=hash_pin(initial_pin),
            role="admin",
            is_active=True,
            must_change_pin=True,
        )
        db.add(default_admin)
        db.commit()
        db.refresh(default_admin)
        logger.warning(
            f"[SECURITY NOTICE] 初期管理アカウントを生成しました。"
            f" Staff ID: {default_admin.staff_id} / Initial PIN: {initial_pin} (初回変更必須)"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("SKIP_SEED", "false").lower() != "true":
        db = SessionLocal()
        try:
            seed_initial_admin(db)
        finally:
            db.close()
    yield


app = FastAPI(title="スポーツボウリング場予約システム API - 第四弾", lifespan=lifespan)
app.include_router(staff.router)
app.include_router(users.router)
app.include_router(gears.router)
app.include_router(sessions.router)
app.include_router(scores.router)
app.include_router(dashboard.router)
app.include_router(class_completion.router)
app.include_router(lanes.router)
app.include_router(badges.router)


def _auto_assign_lane(db: Session) -> int:
    """空いている(available かつ アクティブセッションなし)レーンを、番号が若い順に自動選出する。
    LaneSettings.total_lanesの範囲でLaneレコードが不足していれば自動生成してから選ぶ
    (6レーンへの増設等、設定変更だけで対応できるようにするため)。"""
    settings = db.query(LaneSettings).first()
    if settings is None:
        settings = LaneSettings(total_lanes=4)
        db.add(settings)
        db.commit()
        db.refresh(settings)

    existing_numbers = {lane.lane_number for lane in db.query(Lane).all()}
    for n in range(1, settings.total_lanes + 1):
        if n not in existing_numbers:
            db.add(Lane(lane_number=n, status="available", purpose="general"))
    db.commit()

    active_lane_numbers = {
        s.lane_number for s in db.query(BowlingSession).filter(BowlingSession.status == "active").all()
    }

    candidates = (
        db.query(Lane)
        .filter(Lane.status == "available")
        .order_by(Lane.lane_number)
        .all()
    )
    for lane in candidates:
        if lane.lane_number not in active_lane_numbers:
            return lane.lane_number

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="現在、利用可能な空きレーンがありません。",
    )


@app.post("/api/v1/checkin")
def create_checkin(
    lane_number: Optional[int] = Form(None),
    member_code: Optional[str] = Form(None),
    guest_name: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),  # 本物のスタッフ認証に接続済み
):
    """受付チェックイン（会員検索・警告表示・スタッフID記録・重複チェックイン防止）。
    lane_numberを省略した場合、空いているレーンをシステムが自動選出する（第三弾拡張③）。
    明示的にlane_numberを指定した場合は、これまで通りその番号を使う。"""

    auto_assigned = False
    if lane_number is None:
        lane_number = _auto_assign_lane(db)
        auto_assigned = True

    # 同一レーンにすでにアクティブなセッションがないか確認（夜間CSV照合の一意性を担保）
    existing = (
        db.query(BowlingSession)
        .filter(BowlingSession.lane_number == lane_number, BowlingSession.status == "active")
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"レーン{lane_number}にはすでにアクティブなセッション(session_id={existing.id})が存在します。先にチェックアウトしてください。",
        )

    user = None
    warning_message = None
    if member_code:
        user = db.query(User).filter(User.member_code == member_code).first()
        if not user:
            warning_message = f"会員コード '{member_code}' が見つかりませんでした。ゲストとして登録します。"

    player_name = user.name if user else (guest_name or "ゲスト様")

    session = BowlingSession(
        lane_number=lane_number,
        staff_id=current_staff.staff_id,
        start_time=datetime.utcnow(),
        status="active",
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    player = SessionPlayer(
        session_id=session.id,
        user_id=user.id if user else None,
        player_name=player_name,
    )
    db.add(player)
    db.commit()

    return {
        "message": "チェックインが完了しました",
        "warning": warning_message,
        "session_id": session.id,
        "lane_number": lane_number,
        "lane_auto_assigned": auto_assigned,
        "player_name": player_name,
        "processed_by_staff": current_staff.name,
    }


@app.post("/api/v1/checkout/{session_id}")
def checkout_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    session = db.query(BowlingSession).filter(BowlingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="指定されたセッションが見つかりません")

    if session.status == "completed":
        raise HTTPException(status_code=400, detail="このセッションはすでにチェックアウト済みです")

    session.end_time = datetime.utcnow()
    session.status = "completed"
    db.commit()

    return {"message": f"レーン {session.lane_number} を解放し、チェックアウトを完了しました"}


@app.post("/api/v1/gears/{gear_id}/maintenance")
def reset_gear_maintenance(
    gear_id: int,
    action_type: str = Form("oil_removal"),
    note: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    gear = db.query(Gear).filter(Gear.id == gear_id).first()
    if not gear:
        raise HTTPException(status_code=404, detail="ギアが見つかりません")

    log = MaintenanceLog(
        gear_id=gear.id,
        action_type=action_type,
        games_at_maintenance=gear.total_games,
        note=note,
    )
    db.add(log)
    gear.total_games = 0
    db.commit()

    return {"message": f"ギア '{gear.name}' のメンテナンス履歴を記録し、投球カウンターをリセットしました"}
