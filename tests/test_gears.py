import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.models import Staff, User, Gear, MaintenanceLog
from app.utils.staff_auth import hash_pin


# ============================================================
# テスト用DB
# ============================================================

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


# ============================================================
# テストデータ
# ============================================================

ADMIN_ID = None
MEMBER_ID = None
OTHER_MEMBER_ID = None
GEAR_ID = None


@pytest.fixture(autouse=True)
def setup_database():
    global ADMIN_ID
    global MEMBER_ID
    global OTHER_MEMBER_ID
    global GEAR_ID

    app.dependency_overrides[get_db] = override_get_db

    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()

    admin = Staff(
        name="テスト管理者",
        pin_hash=hash_pin("00001111"),
        role="admin",
        is_active=True,
        must_change_pin=False,
    )

    member = User(
        member_code="M-8823",
        name="純子",
        phone_number="090-0000-0000",
        pin_hash=hash_pin("1234"),
    )

    other_member = User(
        member_code="M-9999",
        name="他人太郎",
        phone_number="090-9999-9999",
        pin_hash=hash_pin("5678"),
    )

    db.add(admin)
    db.add(member)
    db.add(other_member)
    db.commit()

    db.refresh(admin)
    db.refresh(member)
    db.refresh(other_member)

    ADMIN_ID = admin.staff_id
    MEMBER_ID = member.id
    OTHER_MEMBER_ID = other_member.id

    gear = Gear(
        user_id=member.id,
        gear_type="ball",
        name="Storm Phaze II",
        weight_or_size="15lb",
        total_games=34,
        status="active",
        maintenance_reminder_disabled=False,
        maintenance_reminder_snoozed_stage=None,
    )

    db.add(gear)
    db.commit()
    db.refresh(gear)

    GEAR_ID = gear.id

    db.close()

    yield

    Base.metadata.drop_all(bind=engine)


# ============================================================
# 認証ヘルパー
# ============================================================

def admin_headers():
    response = client.post(
        "/api/v1/staff/login",
        json={
            "staff_id": ADMIN_ID,
            "pin_code": "00001111",
        },
    )

    assert response.status_code == 200

    return {
        "Authorization": f"Bearer {response.json()['access_token']}"
    }


def member_headers():
    response = client.post(
        "/api/v1/users/login",
        json={
            "identifier": "M-8823",
            "pin_code": "1234",
        },
    )

    assert response.status_code == 200

    return {
        "Authorization": f"Bearer {response.json()['access_token']}"
    }


def other_member_headers():
    response = client.post(
        "/api/v1/users/login",
        json={
            "identifier": "M-9999",
            "pin_code": "5678",
        },
    )

    assert response.status_code == 200

    return {
        "Authorization": f"Bearer {response.json()['access_token']}"
    }


# ============================================================
# リマインド状態取得
# ============================================================

def test_maintenance_reminder_before_50_games():
    """
    50G未満ではリマインドを表示しない。
    """

    headers = admin_headers()

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["gear_id"] == GEAR_ID
    assert data["games_since_maintenance"] == 34
    assert data["reminder_status"] == "none"
    assert data["reminder_visible"] is False


def test_maintenance_reminder_at_50_games():
    """
    50G到達で「おすすめ」表示。
    """

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.total_games = 50

    db.commit()
    db.close()

    headers = admin_headers()

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["games_since_maintenance"] == 50
    assert data["reminder_status"] == "recommended"
    assert data["reminder_visible"] is True


def test_maintenance_reminder_at_75_games():
    """
    75G到達で「強く推奨」表示。
    """

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.total_games = 75

    db.commit()
    db.close()

    headers = admin_headers()

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["games_since_maintenance"] == 75
    assert data["reminder_status"] == "recommended_strongly"
    assert data["reminder_visible"] is True


def test_maintenance_reminder_at_100_games():
    """
    100G到達でメンテナンス時期。
    """

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.total_games = 100

    db.commit()
    db.close()

    headers = admin_headers()

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["games_since_maintenance"] == 100
    assert data["reminder_status"] == "maintenance_due"
    assert data["reminder_visible"] is True


def test_maintenance_reminder_uses_last_oil_removal_log():
    """
    オイル抜き履歴がある場合、
    total_games全体ではなく最後のオイル抜きからのゲーム数で判定する。
    """

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()

    gear.total_games = 84

    log = MaintenanceLog(
        gear_id=gear.id,
        action_type="oil_removal",
        games_at_maintenance=34,
    )

    db.add(log)
    db.commit()
    db.close()

    headers = admin_headers()

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    # 84 - 34 = 50G
    assert data["games_since_maintenance"] == 50
    assert data["reminder_status"] == "recommended"
    assert data["reminder_visible"] is True


# ============================================================
# 会員側リマインド一覧
# ============================================================

def test_member_can_get_own_maintenance_reminders():
    """
    会員本人は自分のボールのリマインド一覧を取得できる。
    """

    headers = member_headers()

    response = client.get(
        "/api/v1/gears/me/maintenance-reminders",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["gear_id"] == GEAR_ID


def test_member_maintenance_reminders_require_authentication():
    """
    未認証では会員側リマインド一覧を取得できない。
    """

    response = client.get(
        "/api/v1/gears/me/maintenance-reminders"
    )

    assert response.status_code == 401


# ============================================================
# スタッフ側「今回はしない」
# ============================================================

def test_staff_can_snooze_maintenance_reminder():
    """
    スタッフが50Gリマインドを「今回はしない」にすると、
    現在の50G段階では非表示になる。
    """

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.total_games = 50

    db.commit()
    db.close()

    headers = admin_headers()

    response = client.post(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder/snooze",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["gear_id"] == GEAR_ID
    assert data["reminder_disabled"] is False
    assert data["snoozed_stage"] == 50

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["reminder_visible"] is False


def test_snooze_at_50_reappears_at_75():
    """
    50Gで「今回はしない」にした場合、
    75Gになると再表示される。
    """

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.total_games = 50

    db.commit()
    db.close()

    headers = admin_headers()

    response = client.post(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder/snooze",
        headers=headers,
    )

    assert response.status_code == 200

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.total_games = 75

    db.commit()
    db.close()

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["games_since_maintenance"] == 75
    assert data["reminder_status"] == "recommended_strongly"
    assert data["reminder_visible"] is True


def test_snooze_at_75_reappears_at_100():
    """
    75Gで「今回はしない」にした場合、
    100Gになると再表示される。
    """

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.total_games = 75

    db.commit()
    db.close()

    headers = admin_headers()

    response = client.post(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder/snooze",
        headers=headers,
    )

    assert response.status_code == 200

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.total_games = 100

    db.commit()
    db.close()

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["games_since_maintenance"] == 100
    assert data["reminder_status"] == "maintenance_due"
    assert data["reminder_visible"] is True


def test_snooze_at_100_does_not_reappear_above_100():
    """
    100Gで「今回はしない」にした場合、
    100G以上では同じstageのため再表示しない。
    """

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.total_games = 100

    db.commit()
    db.close()

    headers = admin_headers()

    response = client.post(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder/snooze",
        headers=headers,
    )

    assert response.status_code == 200

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.total_games = 120

    db.commit()
    db.close()

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["games_since_maintenance"] == 120
    assert data["reminder_status"] == "none"
    assert data["reminder_visible"] is False


# ============================================================
# 会員側「今回はしない」
# ============================================================

def test_member_can_snooze_own_maintenance_reminder():
    """
    会員本人も自分のボールについて
    「今回はしない」を設定できる。
    """

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.total_games = 50

    db.commit()
    db.close()

    headers = member_headers()

    response = client.post(
        f"/api/v1/gears/me/{GEAR_ID}/maintenance-reminder/snooze",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["gear_id"] == GEAR_ID
    assert data["snoozed_stage"] == 50


def test_other_member_cannot_snooze_someone_elses_gear():
    """
    他会員のボールには「今回はしない」を設定できない。
    """

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.total_games = 50

    db.commit()
    db.close()

    headers = other_member_headers()

    response = client.post(
        f"/api/v1/gears/me/{GEAR_ID}/maintenance-reminder/snooze",
        headers=headers,
    )

    assert response.status_code == 404


# ============================================================
# 「今後も表示しない」
# ============================================================

def test_staff_can_disable_maintenance_reminder():
    """
    スタッフがリマインドを完全停止できる。
    """

    headers = admin_headers()

    response = client.post(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder/disable",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["gear_id"] == GEAR_ID
    assert data["reminder_disabled"] is True

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["reminder_visible"] is False
    assert data["reminder_disabled"] is True


def test_member_can_disable_own_maintenance_reminder():
    """
    会員本人も自分のボールのリマインドを停止できる。
    """

    headers = member_headers()

    response = client.post(
        f"/api/v1/gears/me/{GEAR_ID}/maintenance-reminder/disable",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["gear_id"] == GEAR_ID
    assert data["reminder_disabled"] is True


def test_other_member_cannot_disable_someone_elses_gear():
    """
    他会員のボールのリマインドを停止できない。
    """

    headers = other_member_headers()

    response = client.post(
        f"/api/v1/gears/me/{GEAR_ID}/maintenance-reminder/disable",
        headers=headers,
    )

    assert response.status_code == 404


# ============================================================
# 「リマインドを再開」
# ============================================================

def test_staff_can_enable_maintenance_reminder():
    """
    停止したリマインドをスタッフが再開できる。
    """

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.total_games = 50
    gear.maintenance_reminder_disabled = True
    gear.maintenance_reminder_snoozed_stage = 50

    db.commit()
    db.close()

    headers = admin_headers()

    response = client.post(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder/enable",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["reminder_disabled"] is False
    assert data["snoozed_stage"] is None

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["reminder_visible"] is True
    assert data["reminder_status"] == "recommended"


def test_member_can_enable_own_maintenance_reminder():
    """
    会員本人も自分のボールのリマインドを再開できる。
    """

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.maintenance_reminder_disabled = True
    gear.maintenance_reminder_snoozed_stage = 50
    gear.total_games = 50

    db.commit()
    db.close()

    headers = member_headers()

    response = client.post(
        f"/api/v1/gears/me/{GEAR_ID}/maintenance-reminder/enable",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["reminder_disabled"] is False
    assert data["snoozed_stage"] is None


def test_other_member_cannot_enable_someone_elses_gear():
    """
    他会員のボールのリマインドを再開できない。
    """

    headers = other_member_headers()

    response = client.post(
        f"/api/v1/gears/me/{GEAR_ID}/maintenance-reminder/enable",
        headers=headers,
    )

    assert response.status_code == 404


# ============================================================
# 認証
# ============================================================

def test_staff_maintenance_reminder_requires_authentication():
    """
    スタッフ側のリマインド取得は認証必須。
    """

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder"
    )

    assert response.status_code == 401


def test_staff_snooze_requires_authentication():
    """
    スタッフ側snoozeは認証必須。
    """

    response = client.post(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder/snooze"
    )

    assert response.status_code == 401


def test_staff_disable_requires_authentication():
    """
    スタッフ側disableは認証必須。
    """

    response = client.post(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder/disable"
    )

    assert response.status_code == 401


def test_staff_enable_requires_authentication():
    """
    スタッフ側enableは認証必須。
    """

    response = client.post(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder/enable"
    )

    assert response.status_code == 401


# ============================================================
# ギア所有者チェック
# ============================================================

def test_member_cannot_access_another_members_reminder():
    """
    会員本人以外のGearにはアクセスできない。
    """

    headers = other_member_headers()

    response = client.post(
        f"/api/v1/gears/me/{GEAR_ID}/maintenance-reminder/snooze",
        headers=headers,
    )

    assert response.status_code == 404


# ============================================================
# ボール以外はリマインド対象外
# ============================================================

def test_non_ball_gear_is_not_maintenance_reminder_target():
    """
    ボール以外のギアはオイル抜きリマインド対象外。
    """

    db = TestingSessionLocal()

    non_ball_gear = Gear(
        user_id=MEMBER_ID,
        gear_type="shoes",
        name="Bowling Shoes",
        weight_or_size="27cm",
        total_games=100,
        status="active",
    )

    db.add(non_ball_gear)
    db.commit()
    db.refresh(non_ball_gear)

    gear_id = non_ball_gear.id

    db.close()

    headers = admin_headers()

    response = client.get(
        f"/api/v1/gears/{gear_id}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["reminder_status"] == "none"
    assert data["reminder_visible"] is False


# ============================================================
# 存在しないGear
# ============================================================

def test_maintenance_reminder_for_nonexistent_gear_returns_404():
    """
    存在しないGearは404。
    """

    headers = admin_headers()

    response = client.get(
        "/api/v1/gears/999999/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 404


# ============================================================
# ①の最重要シナリオ
# ============================================================

def test_full_oil_reminder_cycle():
    """
    ①の基本サイクルをまとめて確認。

    34G
      ↓
    50G おすすめ
      ↓
    snooze
      ↓
    75G 強く推奨
      ↓
    snooze
      ↓
    100G メンテナンス時期
      ↓
    オイル抜き
      ↓
    0G相当になりリマインド消滅
    """

    headers = admin_headers()

    # --------------------------------------------------------
    # 34G
    # --------------------------------------------------------

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.total_games = 34

    db.commit()
    db.close()

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["reminder_visible"] is False

    # --------------------------------------------------------
    # 50G
    # --------------------------------------------------------

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.total_games = 50

    db.commit()
    db.close()

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["reminder_status"] == "recommended"
    assert response.json()["reminder_visible"] is True

    # --------------------------------------------------------
    # 50G snooze
    # --------------------------------------------------------

    response = client.post(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder/snooze",
        headers=headers,
    )

    assert response.status_code == 200

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["reminder_visible"] is False

    # --------------------------------------------------------
    # 75G
    # --------------------------------------------------------

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.total_games = 75

    db.commit()
    db.close()

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["reminder_status"] == "recommended_strongly"
    assert response.json()["reminder_visible"] is True

    # --------------------------------------------------------
    # 75G snooze
    # --------------------------------------------------------

    response = client.post(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder/snooze",
        headers=headers,
    )

    assert response.status_code == 200

    # --------------------------------------------------------
    # 100G
    # --------------------------------------------------------

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    gear.total_games = 100

    db.commit()
    db.close()

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["reminder_status"] == "maintenance_due"
    assert response.json()["reminder_visible"] is True

    # --------------------------------------------------------
    # オイル抜き
    # --------------------------------------------------------

    response = client.post(
        f"/api/v1/gears/{GEAR_ID}/maintenance",
        data={
            "action_type": "oil_removal",
            "note": "定期オイル抜き",
        },
        headers=headers,
    )

    assert response.status_code == 200

    # --------------------------------------------------------
    # オイル抜き後はリマインド消滅
    # --------------------------------------------------------

    db = TestingSessionLocal()

    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()

    assert gear.total_games == 0

    logs = (
        db.query(MaintenanceLog)
        .filter(MaintenanceLog.gear_id == GEAR_ID)
        .all()
    )

    assert len(logs) == 1
    assert logs[0].action_type == "oil_removal"
    assert logs[0].games_at_maintenance == 100

    db.close()

    response = client.get(
        f"/api/v1/gears/{GEAR_ID}/maintenance-reminder",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["games_since_maintenance"] == 0
    assert data["reminder_status"] == "none"
    assert data["reminder_visible"] is False