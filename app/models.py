from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class Staff(Base):
    """スタッフ認証モデル（6ラウンドのレビューで確定した本線版）"""
    __tablename__ = "staffs"

    staff_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    pin_hash = Column(String(100), nullable=False)
    role = Column(String(20), default="staff", nullable=False)  # 'staff' or 'admin'
    is_active = Column(Boolean, default=True, nullable=False)
    failed_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)
    must_change_pin = Column(Boolean, default=False, nullable=False)

    sessions = relationship("BowlingSession", back_populates="staff")


class User(Base):
    """会員モデル"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    member_code = Column(String(20), unique=True, index=True, nullable=False)
    name = Column(String(50), nullable=False)
    phone_number = Column(String(20), unique=True, index=True, nullable=False)
    pin_hash = Column(String(100), nullable=True)  # 未設定(スタッフ受付登録直後)はNULL
    failed_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    gears = relationship("Gear", back_populates="user")
    players = relationship("SessionPlayer", back_populates="user")

    @property
    def has_pin(self) -> bool:
        return self.pin_hash is not None


class Gear(Base):
    """マイギア管理モデル"""
    __tablename__ = "gears"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    gear_type = Column(String(20), nullable=False)  # 'ball' or 'shoes'
    name = Column(String(100), nullable=False)
    weight_or_size = Column(String(20))
    total_games = Column(Integer, default=0)
    status = Column(String(20), default="active")

    user = relationship("User", back_populates="gears")
    maintenance_logs = relationship("MaintenanceLog", back_populates="gear")
    games = relationship("Game", back_populates="gear")


class MaintenanceLog(Base):
    """ギアメンテナンス（オイル抜き等）履歴"""
    __tablename__ = "maintenance_logs"

    id = Column(Integer, primary_key=True, index=True)
    gear_id = Column(Integer, ForeignKey("gears.id", ondelete="CASCADE"), nullable=False)
    action_type = Column(String(50), nullable=False)
    games_at_maintenance = Column(Integer, nullable=False)
    performed_at = Column(DateTime, default=datetime.utcnow)
    note = Column(Text, nullable=True)

    gear = relationship("Gear", back_populates="maintenance_logs")


class BowlingSession(Base):
    """レーン割り当てセッション（アメリカン方式・複数人対応）"""
    __tablename__ = "bowling_sessions"

    id = Column(Integer, primary_key=True, index=True)
    lane_number = Column(Integer, nullable=False)
    staff_id = Column(Integer, ForeignKey("staffs.staff_id", ondelete="SET NULL"), nullable=True)
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    status = Column(String(20), default="active")  # 'active', 'completed'

    staff = relationship("Staff", back_populates="sessions")
    players = relationship("SessionPlayer", back_populates="session")


class SessionPlayer(Base):
    """同一レーン内のプレイヤー紐付け中間テーブル"""
    __tablename__ = "session_players"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("bowling_sessions.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    player_name = Column(String(50), nullable=False)
    player_order = Column(Integer, default=1)

    session = relationship("BowlingSession", back_populates="players")
    user = relationship("User", back_populates="players")
    games = relationship("Game", back_populates="player")


class Game(Base):
    """ゲームデータ（ギア紐付け対応）"""
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("session_players.id", ondelete="CASCADE"), nullable=False)
    gear_id = Column(Integer, ForeignKey("gears.id", ondelete="SET NULL"), nullable=True)
    game_number = Column(Integer, nullable=False)
    total_score = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    player = relationship("SessionPlayer", back_populates="games")
    gear = relationship("Gear", back_populates="games")
    frames = relationship("Frame", back_populates="game", cascade="all, delete-orphan")


class Frame(Base):
    """1〜10フレーム詳細（レベル3データ）"""
    __tablename__ = "frames"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    frame_number = Column(Integer, nullable=False)
    score = Column(Integer, nullable=True)

    game = relationship("Game", back_populates="frames")
    shots = relationship("Shot", back_populates="frame", cascade="all, delete-orphan")


class Shot(Base):
    """1投ごとのピン倒数・残りピンパターン（10番ピン分析用）"""
    __tablename__ = "shots"

    id = Column(Integer, primary_key=True, index=True)
    frame_id = Column(Integer, ForeignKey("frames.id", ondelete="CASCADE"), nullable=False)
    shot_number = Column(Integer, nullable=False)
    pins_knocked = Column(Integer, nullable=False)
    remaining_pins = Column(String(20), nullable=True)  # 例: "10" または "7,10"

    frame = relationship("Frame", back_populates="shots")


class Reservation(Base):
    """予約モデル（第一弾から継続、staff.pyのstaff_update_reservationが参照する最小構成）"""
    __tablename__ = "reservations"

    reservation_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    lane_number = Column(Integer, nullable=True)
    reserved_date = Column(DateTime, nullable=True)
    status = Column(String(20), default="confirmed")
