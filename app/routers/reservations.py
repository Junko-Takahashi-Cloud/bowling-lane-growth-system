from fastapi import APIRouter
from sqlalchemy.orm import Session
from app.models import Reservation
from app.schemas import ReservationUpdate

router = APIRouter(prefix="/api/v1/reservations", tags=["reservations"])


def _apply_reservation_update(db: Session, reservation: Reservation, payload: ReservationUpdate) -> Reservation:
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(reservation, field, value)
    db.commit()
    db.refresh(reservation)
    return reservation
