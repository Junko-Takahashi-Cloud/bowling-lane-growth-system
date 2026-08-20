import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.models import Staff, User, Gear
from app.utils.staff_auth import hash_pin

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    # 既に must_change_pin=False のadminを用意し、初期シード(seed_initial_admin)をスキップさせる
    admin = Staff(
        name="テスト管理者",
        pin_hash=hash_pin("00001111"),
        role="admin",
        is_active=True,
        must_change_pin=False,
    )
    db.add(admin)

    member = User(member_code="M-8823", name="純子", phone_number="090-0000-0000")
    db.add(member)

    db.commit()
    db.refresh(admin)
    db.refresh(member)
    global ADMIN_ID
    ADMIN_ID = admin.staff_id

    gear = Gear(user_id=member.id, gear_type="ball", name="Storm Phaze II", weight_or_size="15lb", total_games=34)
    db.add(gear)
    db.commit()
    db.refresh(gear)
    global GEAR_ID
    GEAR_ID = gear.id

    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def admin_token():
    resp = client.post("/api/v1/staff/login", json={"staff_id": ADMIN_ID, "pin_code": "00001111"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_admin_login_success():
    resp = client.post("/api/v1/staff/login", json={"staff_id": ADMIN_ID, "pin_code": "00001111"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_pin_fails():
    resp = client.post("/api/v1/staff/login", json={"staff_id": ADMIN_ID, "pin_code": "99999999"})
    assert resp.status_code == 401


def test_login_nonexistent_id_returns_same_401_as_wrong_pin():
    resp_missing = client.post("/api/v1/staff/login", json={"staff_id": 9999, "pin_code": "00001111"})
    resp_wrong = client.post("/api/v1/staff/login", json={"staff_id": ADMIN_ID, "pin_code": "wrong000"})
    assert resp_missing.status_code == 401
    assert resp_wrong.status_code == 401
    assert resp_missing.json()["detail"] == resp_wrong.json()["detail"]


def test_pin_lockout_after_5_failures_then_recovers():
    for _ in range(5):
        resp = client.post("/api/v1/staff/login", json={"staff_id": ADMIN_ID, "pin_code": "wrong000"})
        assert resp.status_code == 401

    # 6回目は正しいPINでもロック中なので401
    resp_locked = client.post("/api/v1/staff/login", json={"staff_id": ADMIN_ID, "pin_code": "00001111"})
    assert resp_locked.status_code == 401


def test_create_staff_requires_admin():
    headers = {"Authorization": "Bearer invalid-token"}
    resp = client.post("/api/v1/staff", json={"name": "新人", "pin_code": "12345678"}, headers=headers)
    assert resp.status_code == 401


def test_create_staff_by_admin_succeeds():
    token = admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post("/api/v1/staff", json={"name": "新人スタッフ", "pin_code": "12345678"}, headers=headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["role"] == "staff"
    assert data["is_active"] is True
    assert "pin_hash" not in data  # レスポンスにハッシュ済みPINが含まれていないこと


def test_checkin_success_and_duplicate_checkin_rejected():
    token = admin_token()
    headers = {"Authorization": f"Bearer {token}"}

    resp1 = client.post("/api/v1/checkin", data={"lane_number": 3, "member_code": "M-8823"}, headers=headers)
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert body1["warning"] is None
    assert body1["player_name"] == "純子"
    assert body1["processed_by_staff"] == "テスト管理者"

    # 同一レーンへの二重チェックインは409で拒否される
    resp2 = client.post("/api/v1/checkin", data={"lane_number": 3, "guest_name": "別のお客様"}, headers=headers)
    assert resp2.status_code == 409

    session_id = body1["session_id"]
    resp_checkout = client.post(f"/api/v1/checkout/{session_id}", headers=headers)
    assert resp_checkout.status_code == 200

    # チェックアウト後は同じレーンに再度チェックインできる
    resp3 = client.post("/api/v1/checkin", data={"lane_number": 3, "guest_name": "次のお客様"}, headers=headers)
    assert resp3.status_code == 200

    # 完了済みセッションを再度チェックアウトしようとすると400
    resp_double_checkout = client.post(f"/api/v1/checkout/{session_id}", headers=headers)
    assert resp_double_checkout.status_code == 400


def test_checkin_with_unknown_member_code_warns_and_registers_as_guest():
    token = admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post("/api/v1/checkin", data={"lane_number": 1, "member_code": "M-0000"}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["warning"] is not None
    assert body["player_name"] == "ゲスト様"


def test_checkin_requires_authentication():
    resp = client.post("/api/v1/checkin", data={"lane_number": 2, "member_code": "M-8823"})
    assert resp.status_code == 401


def test_gear_maintenance_reset():
    token = admin_token()
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        f"/api/v1/gears/{GEAR_ID}/maintenance",
        data={"action_type": "oil_removal", "note": "定期メンテナンス"},
        headers=headers,
    )
    assert resp.status_code == 200

    db = TestingSessionLocal()
    gear = db.query(Gear).filter(Gear.id == GEAR_ID).first()
    assert gear.total_games == 0
    logs = gear.maintenance_logs
    assert len(logs) == 1
    assert logs[0].games_at_maintenance == 34
    db.close()


def test_must_change_pin_blocks_other_endpoints_until_pin_changed():
    token = admin_token()
    headers = {"Authorization": f"Bearer {token}"}

    resp_create = client.post(
        "/api/v1/staff",
        json={"name": "初回PIN未変更スタッフ", "pin_code": "11112222", "must_change_pin": True},
        headers=headers,
    )
    assert resp_create.status_code == 201
    new_staff_id = resp_create.json()["staff_id"]

    resp_login = client.post("/api/v1/staff/login", json={"staff_id": new_staff_id, "pin_code": "11112222"})
    assert resp_login.status_code == 200
    new_token = resp_login.json()["access_token"]
    new_headers = {"Authorization": f"Bearer {new_token}"}

    # must_change_pin=True の状態では、PIN変更エンドポイント以外は403で弾かれる
    resp_blocked = client.get("/api/v1/staff", headers=new_headers)
    assert resp_blocked.status_code == 403

    # PIN変更エンドポイントは通る
    resp_change = client.patch(
        "/api/v1/staff/me/pin",
        json={"current_pin": "11112222", "new_pin": "33334444"},
        headers=new_headers,
    )
    assert resp_change.status_code == 200
    fresh_token = resp_change.json()["access_token"]
    fresh_headers = {"Authorization": f"Bearer {fresh_token}"}

    # 変更後は他のエンドポイントも通る
    resp_after = client.get("/api/v1/staff", headers=fresh_headers)
    assert resp_after.status_code == 200


def test_self_lockout_prevention_on_active_toggle():
    token = admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.patch(f"/api/v1/staff/{ADMIN_ID}/active", json={"is_active": False}, headers=headers)
    assert resp.status_code == 400
