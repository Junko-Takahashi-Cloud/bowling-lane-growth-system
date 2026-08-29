from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AchievementBadge, User
from app.schemas import BadgeOut, BadgeEvaluateResponse
from app.utils.access_control import require_staff_or_self
from app.services.badge_criteria import BADGE_CRITERIA

router = APIRouter(prefix="/api/v1/badges", tags=["badges"])


@router.post("/evaluate/{user_id}", response_model=BadgeEvaluateResponse)
def evaluate_badges(
    user_id: int,
    db: Session = Depends(get_db),
    _auth=Depends(require_staff_or_self()),
):
    """現在の成績・データをもとにバッジの達成条件を評価し、新規達成分を付与する。
    第三弾拡張③の中心機能。判定条件自体はapp/services/badge_criteria.pyで定義し、
    ここでは「評価して付与する」という仕組みのみを担う。"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会員が見つかりません")

    already_achieved = {
        b.badge_code for b in db.query(AchievementBadge).filter(AchievementBadge.user_id == user_id).all()
    }

    newly_achieved = []
    for badge_code, (_, criterion_fn) in BADGE_CRITERIA.items():
        if badge_code in already_achieved:
            continue
        if criterion_fn(user_id, db):
            badge = AchievementBadge(user_id=user_id, badge_code=badge_code)
            db.add(badge)
            newly_achieved.append(badge)

    db.commit()
    for b in newly_achieved:
        db.refresh(b)

    return BadgeEvaluateResponse(
        newly_achieved=newly_achieved,
        message=f"{len(newly_achieved)}件のバッジを新たに達成しました" if newly_achieved else "新規達成はありませんでした",
    )


@router.get("/user/{user_id}", response_model=list[BadgeOut])
def list_badges(
    user_id: int,
    db: Session = Depends(get_db),
    _auth=Depends(require_staff_or_self()),
):
    """会員の獲得済みバッジ一覧。スタッフは誰でも、会員は本人のみ閲覧可能。"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会員が見つかりません")
    return (
        db.query(AchievementBadge)
        .filter(AchievementBadge.user_id == user_id)
        .order_by(AchievementBadge.achieved_at.desc())
        .all()
    )
