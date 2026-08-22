from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import ClassCompletionRecord, User, Staff
from app.schemas import ClassCompletionCreate, ClassCompletionOut
from app.utils.staff_auth import get_current_staff
from app.utils.access_control import require_staff_or_self

router = APIRouter(prefix="/api/v1/class-completions", tags=["class-completions"])


@router.post("", response_model=ClassCompletionOut, status_code=status.HTTP_201_CREATED)
def record_class_completion(
    payload: ClassCompletionCreate,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    """初心者教室の修了を記録する（第三弾拡張④）。
    external_course_idは第三弾ClassCourse.course_idの値であり、本アプリのDBには存在しない
    （別アプリ・別DBのため）ので、存在確認は行わない。スタッフが第三弾側の情報を見ながら
    手動で紐付けて登録する運用を前提とする（設計メモ: docs/phase3_extension_class_completion.md）。"""
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会員が見つかりません")

    record = ClassCompletionRecord(
        user_id=payload.user_id,
        external_course_id=payload.external_course_id,
        recorded_by_staff_id=current_staff.staff_id,
    )
    if payload.completed_at is not None:
        record.completed_at = payload.completed_at

    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/user/{user_id}", response_model=list[ClassCompletionOut])
def list_class_completions(
    user_id: int,
    db: Session = Depends(get_db),
    _auth=Depends(require_staff_or_self()),
):
    """会員の教室修了記録一覧。スタッフは誰でも、会員は本人のみ閲覧可能。"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会員が見つかりません")
    return (
        db.query(ClassCompletionRecord)
        .filter(ClassCompletionRecord.user_id == user_id)
        .order_by(ClassCompletionRecord.completed_at.desc())
        .all()
    )
