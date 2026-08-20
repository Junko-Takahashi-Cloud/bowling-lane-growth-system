from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Game, Frame, Shot, SessionPlayer
from app.schemas import MemberDashboardResponse, RecentGameSummary
from app.utils.access_control import require_staff_or_self

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/member/{user_id}", response_model=MemberDashboardResponse)
def get_member_dashboard(
    user_id: int,
    db: Session = Depends(get_db),
    _auth=Depends(require_staff_or_self()),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会員が見つかりません")

    # この会員が(複数人セッションも含め)プレイした全ゲームを取得
    player_ids = [p.id for p in db.query(SessionPlayer).filter(SessionPlayer.user_id == user_id).all()]

    if not player_ids:
        return MemberDashboardResponse(
            user_id=user.id,
            user_name=user.name,
            total_games=0,
            average_score=0.0,
            high_score=0,
            low_score=0,
            strike_rate=0.0,
            spare_rate=0.0,
            pin10_leave_rate=0.0,
            recent_games=[],
        )

    games = (
        db.query(Game)
        .filter(Game.player_id.in_(player_ids))
        .order_by(Game.created_at.desc())
        .all()
    )

    if not games:
        return MemberDashboardResponse(
            user_id=user.id,
            user_name=user.name,
            total_games=0,
            average_score=0.0,
            high_score=0,
            low_score=0,
            strike_rate=0.0,
            spare_rate=0.0,
            pin10_leave_rate=0.0,
            recent_games=[],
        )

    scores = [g.total_score for g in games]
    total_games = len(games)
    average_score = round(sum(scores) / total_games, 2)
    high_score = max(scores)
    low_score = min(scores)

    game_ids = [g.id for g in games]
    all_frames = db.query(Frame).filter(Frame.game_id.in_(game_ids)).all()
    total_frames = len(all_frames)

    strikes = 0
    spares = 0
    pin10_leaves = 0

    for frame in all_frames:
        shots = sorted(frame.shots, key=lambda s: s.shot_number)
        if not shots:
            continue

        if frame.frame_number <= 9:
            if shots[0].pins_knocked == 10:
                strikes += 1
            elif len(shots) >= 2 and shots[0].pins_knocked + shots[1].pins_knocked == 10:
                spares += 1
        else:  # 10フレーム目
            if shots[0].pins_knocked == 10:
                strikes += 1
            elif len(shots) >= 2 and shots[0].pins_knocked + shots[1].pins_knocked == 10:
                spares += 1

        # 10番ピン残り判定（remaining_pinsに"10"が含まれる投球が1つでもあればカウント）
        if any(s.remaining_pins and "10" in s.remaining_pins.split(",") for s in shots):
            pin10_leaves += 1

    strike_rate = round((strikes / total_frames) * 100, 2) if total_frames > 0 else 0.0
    spare_rate = round((spares / total_frames) * 100, 2) if total_frames > 0 else 0.0
    pin10_leave_rate = round((pin10_leaves / total_frames) * 100, 2) if total_frames > 0 else 0.0

    recent_games = [
        RecentGameSummary(game_id=g.id, created_at=g.created_at, total_score=g.total_score)
        for g in games[:5]
    ]

    return MemberDashboardResponse(
        user_id=user.id,
        user_name=user.name,
        total_games=total_games,
        average_score=average_score,
        high_score=high_score,
        low_score=low_score,
        strike_rate=strike_rate,
        spare_rate=spare_rate,
        pin10_leave_rate=pin10_leave_rate,
        recent_games=recent_games,
    )
