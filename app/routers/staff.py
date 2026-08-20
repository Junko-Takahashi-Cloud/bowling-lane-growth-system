from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Staff, Reservation
from app.schemas import (
    StaffCreate, StaffOut, StaffLogin, StaffActiveUpdate, StaffToken,
    ReservationUpdate, ReservationOut, StaffPinUpdate,
)
from app.utils.staff_auth import (
    hash_pin,
    verify_pin,
    authenticate_staff_by_id_and_pin,
    create_staff_access_token,
    get_current_staff,
    require_admin_staff,
)
from app.routers.reservations import _apply_reservation_update

router = APIRouter(prefix="/api/v1/staff", tags=["staff"])


@router.post("", response_model=StaffOut, status_code=status.HTTP_201_CREATED)
def create_staff(
    payload: StaffCreate,
    db: Session = Depends(get_db),
    admin_staff: Staff = Depends(require_admin_staff),
):
    staff = Staff(
        name=payload.name,
        pin_hash=hash_pin(payload.pin_code),
        role=payload.role,
        is_active=True,
        must_change_pin=payload.must_change_pin,
    )
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return staff


@router.post("/login", response_model=StaffToken)
def staff_login(payload: StaffLogin, db: Session = Depends(get_db)):
    staff = authenticate_staff_by_id_and_pin(db, payload.staff_id, payload.pin_code)
    if staff is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="スタッフIDまたはPINが正しくありません",
        )
    token = create_staff_access_token(staff.staff_id, staff.role, must_change_pin=staff.must_change_pin)
    return StaffToken(access_token=token)


@router.patch("/me/pin", response_model=StaffToken)
def update_own_pin(
    payload: StaffPinUpdate,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    if not verify_pin(payload.current_pin, current_staff.pin_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="現在のPINが正しくありません",
        )

    current_staff.pin_hash = hash_pin(payload.new_pin)
    current_staff.must_change_pin = False
    db.commit()
    db.refresh(current_staff)

    token = create_staff_access_token(current_staff.staff_id, current_staff.role, must_change_pin=False)
    return StaffToken(access_token=token)


@router.get("", response_model=list[StaffOut])
def list_staff(
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    return db.query(Staff).all()


@router.patch("/{staff_id}/active", response_model=StaffOut)
def update_staff_active(
    staff_id: int,
    payload: StaffActiveUpdate,
    db: Session = Depends(get_db),
    admin_staff: Staff = Depends(require_admin_staff),
):
    if admin_staff.staff_id == staff_id and not payload.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="自分自身のアカウントを無効化することはできません",
        )

    staff = db.query(Staff).filter(Staff.staff_id == staff_id).first()
    if staff is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="スタッフが見つかりません")

    staff.is_active = payload.is_active
    db.commit()
    db.refresh(staff)
    return staff


@router.patch("/reservations/{reservation_id}", response_model=ReservationOut)
def staff_update_reservation(
    reservation_id: int,
    payload: ReservationUpdate,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    reservation = db.query(Reservation).filter(
        Reservation.reservation_id == reservation_id
    ).first()
    if reservation is None:
        raise HTTPException(status_code=404, detail="予約が見つかりません")

    return _apply_reservation_update(db, reservation, payload)
