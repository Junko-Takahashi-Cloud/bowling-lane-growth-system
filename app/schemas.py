from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class StaffCreate(BaseModel):
    name: str
    pin_code: str
    role: str = "staff"
    must_change_pin: bool = False


class StaffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    staff_id: int
    name: str
    role: str
    is_active: bool
    must_change_pin: bool


class StaffLogin(BaseModel):
    staff_id: int
    pin_code: str


class StaffActiveUpdate(BaseModel):
    is_active: bool


class StaffToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class StaffPinUpdate(BaseModel):
    current_pin: str
    new_pin: str


class ReservationUpdate(BaseModel):
    status: Optional[str] = None
    lane_number: Optional[int] = None
    reserved_date: Optional[datetime] = None


class ReservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    reservation_id: int
    lane_number: Optional[int] = None
    reserved_date: Optional[datetime] = None
    status: str


class UserCreate(BaseModel):
    member_code: str
    name: str
    phone_number: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    member_code: str
    name: str
    phone_number: str
    created_at: datetime
    has_pin: bool = False


class UserLogin(BaseModel):
    identifier: str
    pin_code: str


class UserToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserSetInitialPin(BaseModel):
    member_code: str
    phone_number: str
    pin_code: str


class UserPinUpdate(BaseModel):
    current_pin: str
    new_pin: str


class GearCreate(BaseModel):
    user_id: int
    gear_type: str
    name: str
    weight_or_size: Optional[str] = None


class GearSelfCreate(BaseModel):
    gear_type: str
    name: str
    weight_or_size: Optional[str] = None


class GearOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    gear_type: str
    name: str
    weight_or_size: Optional[str] = None
    total_games: int
    status: str
    maintenance_reminder_disabled: bool = False
    maintenance_reminder_snoozed_stage: Optional[int] = None


class MaintenanceReminderOut(BaseModel):
    gear_id: int
    gear_name: str
    games_since_maintenance: int
    reminder_status: str
    reminder_message: Optional[str] = None
    reminder_visible: bool
    reminder_disabled: bool
    snoozed_stage: Optional[int] = None


class MaintenanceReminderActionOut(BaseModel):
    gear_id: int
    reminder_disabled: bool
    snoozed_stage: Optional[int] = None
    message: str


class SessionPlayerAdd(BaseModel):
    member_code: Optional[str] = None
    guest_name: Optional[str] = None


class SessionPlayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    session_id: int
    user_id: Optional[int] = None
    player_name: str
    player_order: int


class ShotInput(BaseModel):
    pins_knocked: int
    remaining_pins: Optional[str] = None


class FrameInput(BaseModel):
    frame_number: int
    shots: list[ShotInput]


class GameImportInput(BaseModel):
    player_id: int
    gear_id: Optional[int] = None
    game_number: int
    frames: list[FrameInput]


class ScoreImportRequest(BaseModel):
    games: list[GameImportInput]


class GameImportResult(BaseModel):
    game_id: int
    player_id: int
    total_score: int


class ScoreImportResponse(BaseModel):
    imported_games: list[GameImportResult]
    message: str


class RecentGameSummary(BaseModel):
    game_id: int
    created_at: datetime
    total_score: int


class MemberDashboardResponse(BaseModel):
    user_id: int
    user_name: str
    total_games: int
    average_score: float
    high_score: int
    low_score: int
    strike_rate: float
    spare_rate: float
    pin10_leave_rate: float
    recent_games: list[RecentGameSummary]


class LaneSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    total_lanes: int


class LaneSettingsUpdate(BaseModel):
    total_lanes: int


class LaneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lane_number: int
    status: str
    purpose: str


class LaneStatusUpdate(BaseModel):
    status: str


class LanePurposeUpdate(BaseModel):
    purpose: str


class BadgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    badge_code: str
    achieved_at: datetime


class BadgeEvaluateResponse(BaseModel):
    newly_achieved: list[BadgeOut]
    message: str


class ClassCompletionCreate(BaseModel):
    user_id: int
    external_course_id: int
    completed_at: Optional[datetime] = None


class ClassCompletionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    external_course_id: int
    completed_at: datetime
    recorded_by_staff_id: int
