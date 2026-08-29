from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class Staff(Base):
    __tablename__ = "staffs"
    staff_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    pin_hash = Column(String(100), nullable=False)
    role = Column(String(20), default="staff", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    failed_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)
    must_change_pin = Column(Boolean, default=False, nullable=False)
    sessions = relationship("BowlingSession", back_populates="staff")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    member_code = Column(String(20), unique=True, index=True, nullable=False)
    name = Column(String(50), nullable=False)
    phone_number = Column(String(20), unique=True, index=True, nullable=False)
    pin_hash = Column(String(100), nullable=True)
    failed_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    gears = relationship("Gear", back_populates="user")
    players = relationship("SessionPlayer", back_populates="user")

    @property
    def has_pin(self) -> bool:
        return self.pin_hash is not None


class Gear(Base):
    __tablename__ = "gears"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    gear_type = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    weight_or_size = Column(String(20))
    total_games = Column(Integer, default=0)
    status = Column(String(20), default="active")

    # 第三弾拡張①: オイル抜きリマインド
    maintenance_reminder_disabled = Column(Boolean, default=False, nullable=False)
    maintenance_reminder_snoozed_stage = Column(Integer, nullable=True)

    user = relationship("User", back_populates="gears")
    maintenance_logs = relationship("MaintenanceLog", back_populates="gear")
    games = relationship("Game", back_populates="gear")

    @property
    def games_since_maintenance(self) -> int:
        """直近のメンテナンス実施時からの投球数。
        メンテナンス記録がなければ、ギア登録からの総投球数をそのまま使う。"""
        if not self.maintenance_logs:
            return self.total_games
        last_log = max(self.maintenance_logs, key=lambda log: log.performed_at)
        return self.total_games - last_log.games_at_maintenance


class MaintenanceLog(Base):
    __tablename__ = "maintenance_logs"
    id = Column(Integer, primary_key=True, index=True)
    gear_id = Column(Integer, ForeignKey("gears.id", ondelete="CASCADE"), nullable=False)
    action_type = Column(String(50), nullable=False)
    games_at_maintenance = Column(Integer, nullable=False)
    performed_at = Column(DateTime, default=datetime.utcnow)
    note = Column(Text, nullable=True)
    gear = relationship("Gear", back_populates="maintenance_logs")


class BowlingSession(Base):
    __tablename__ = "bowling_sessions"
    id = Column(Integer, primary_key=True, index=True)
    lane_number = Column(Integer, nullable=False)
    staff_id = Column(Integer, ForeignKey("staffs.staff_id", ondelete="SET NULL"), nullable=True)
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    status = Column(String(20), default="active")
    staff = relationship("Staff", back_populates="sessions")
    players = relationship("SessionPlayer", back_populates="session")


class SessionPlayer(Base):
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
    __tablename__ = "frames"
    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    frame_number = Column(Integer, nullable=False)
    score = Column(Integer, nullable=True)
    game = relationship("Game", back_populates="frames")
    shots = relationship("Shot", back_populates="frame", cascade="all, delete-orphan")


class Shot(Base):
    __tablename__ = "shots"
    id = Column(Integer, primary_key=True, index=True)
    frame_id = Column(Integer, ForeignKey("frames.id", ondelete="CASCADE"), nullable=False)
    shot_number = Column(Integer, nullable=False)
    pins_knocked = Column(Integer, nullable=False)
    remaining_pins = Column(String(20), nullable=True)
    frame = relationship("Frame", back_populates="shots")


class Reservation(Base):
    __tablename__ = "reservations"
    reservation_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    lane_number = Column(Integer, nullable=True)
    reserved_date = Column(DateTime, nullable=True)
    status = Column(String(20), default="confirmed")


class LaneSettings(Base):
    """店舗全体のレーン設定（第三弾拡張③）。1行のみ運用するシングルトン的テーブル。
    total_lanesを変更するだけで、6レーン等への拡張に対応できるようにする。"""

    __tablename__ = "lane_settings"

    id = Column(Integer, primary_key=True, index=True)
    total_lanes = Column(Integer, nullable=False, default=4)


class Lane(Base):
    """レーン個別の状態管理（第三弾拡張③）。
    lane_numberは1〜LaneSettings.total_lanesの範囲を想定する（アプリ側で整合を保つ。
    DB制約としては強制しない）。"""

    __tablename__ = "lanes"

    id = Column(Integer, primary_key=True, index=True)
    lane_number = Column(Integer, nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="available")  # 'available' / 'maintenance' / 'broken'
    purpose = Column(String(20), nullable=False, default="general")  # 'general' / 'class' / 'competitor'


class AchievementBadge(Base):
    """会員が達成したバッジ・称号の記録（第三弾拡張③）。
    badge_codeの判定ロジックはapp/services/badge_criteria.pyにコード側で定義し、
    ここでは「付与された結果」のみを記録する。"""

    __tablename__ = "achievement_badges"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    badge_code = Column(String(50), nullable=False)
    achieved_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "badge_code", name="uq_user_badge"),
    )

    user = relationship("User")


class ClassCompletionRecord(Base):
    """初心者教室修了記録（第三弾拡張④）。
    第四弾では「初心者教室を修了し、一般ボウラーとして利用可能になった」という
    事実のみを管理する。出席回数・各回の指導内容・適性評価は持たない。
    external_course_idは第三弾ClassCourse.course_idの参照値であり、
    別データベースのためFKではない。"""

    __tablename__ = "class_completion_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    external_course_id = Column(Integer, nullable=False)
    completed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    recorded_by_staff_id = Column(Integer, ForeignKey("staffs.staff_id"), nullable=False)

    user = relationship("User")
