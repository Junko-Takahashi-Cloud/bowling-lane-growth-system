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


# --- ③会員管理 ---

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
    identifier: str  # 会員コード または 電話番号
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


# --- ②マイギア管理 ---

class GearCreate(BaseModel):
    """スタッフ代理登録用（対象会員をuser_idで指定）"""
    user_id: int
    gear_type: str  # 'ball' or 'shoes'
    name: str
    weight_or_size: Optional[str] = None


class GearSelfCreate(BaseModel):
    """会員セルフ登録用（対象会員はトークンの本人で固定するため、user_idは受け取らない）"""
    gear_type: str  # 'ball' or 'shoes'
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


# --- ①複数人セッション ---

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


# --- ⑤Frame/Shot 実データ投入（④Gear紐付けを含む） ---

class ShotInput(BaseModel):
    pins_knocked: int
    remaining_pins: Optional[str] = None


class FrameInput(BaseModel):
    frame_number: int
    shots: list[ShotInput]


class GameImportInput(BaseModel):
    player_id: int  # SessionPlayer.id（夜間CSV照合はレーン+時間帯からplayer_idを特定した後の想定）
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


# --- ⑥成長ダッシュボード ---

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
    pin10_leave_rate: float  # 10番ピン残り率（10番ピン克服率の裏返し指標）
    recent_games: list[RecentGameSummary]
