from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import BowlingSession, SessionPlayer, User, Staff
from app.schemas import SessionPlayerAdd, SessionPlayerOut
from app.utils.staff_auth import get_current_staff

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


@router.post("/{session_id}/players", response_model=SessionPlayerOut, status_code=status.HTTP_201_CREATED)
def add_player_to_session(
    session_id: int,
    payload: SessionPlayerAdd,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    """アメリカン方式など、同一レーンに複数人が同席する場合に、既存セッションへプレイヤーを追加する"""
    bowling_session = db.query(BowlingSession).filter(BowlingSession.id == session_id).first()
    if not bowling_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定されたセッションが見つかりません")
    if bowling_session.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="このセッションはすでに終了しているため、プレイヤーを追加できません",
        )

    user = None
    if payload.member_code:
        user = db.query(User).filter(User.member_code == payload.member_code).first()

    player_name = user.name if user else (payload.guest_name or "ゲスト様")
    next_order = len(bowling_session.players) + 1

    player = SessionPlayer(
        session_id=session_id,
        user_id=user.id if user else None,
        player_name=player_name,
        player_order=next_order,
    )
    db.add(player)
    db.commit()
    db.refresh(player)
    return player


@router.get("/{session_id}/players", response_model=list[SessionPlayerOut])
def list_players_in_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    bowling_session = db.query(BowlingSession).filter(BowlingSession.id == session_id).first()
    if not bowling_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定されたセッションが見つかりません")
    return bowling_session.players
