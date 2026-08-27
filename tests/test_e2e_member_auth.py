import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.models import Staff, User
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

    admin = Staff(
        name="テスト管理者", pin_hash=hash_pin("00001111"), role="admin", is_active=True, must_change_pin=False
    )
    db.add(admin)

    member = User(member_code="M-8823", name="純子", phone_number="090-0000-0000")
    db.add(member)

    other_member = User(member_code="M-9999", name="他人太郎", phone_number="090-9999-9999")
    db.add(other_member)

    db.commit()
    db.refresh(admin)
    db.refresh(member)
    db.refresh(other_member)

    global ADMIN_ID, MEMBER_ID, OTHER_MEMBER_ID
    ADMIN_ID = admin.staff_id
    MEMBER_ID = member.id
    OTHER_MEMBER_ID = other_member.id

    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def admin_headers():
    resp = client.post("/api/v1/staff/login", json={"staff_id": ADMIN_ID, "pin_code": "00001111"})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# --- 初回PIN設定 ---

def test_set_initial_pin_success_and_returns_token():
    resp = client.post(
        "/api/v1/users/set-initial-pin",
        json={"member_code": "M-8823", "phone_number": "090-0000-0000", "pin_code": "1234"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_set_initial_pin_wrong_phone_rejected():
    resp = client.post(
        "/api/v1/users/set-initial-pin",
        json={"member_code": "M-8823", "phone_number": "090-0000-9999", "pin_code": "1234"},
    )
    assert resp.status_code == 401


def test_set_initial_pin_twice_rejected():
    resp1 = client.post(
        "/api/v1/users/set-initial-pin",
        json={"member_code": "M-8823", "phone_number": "090-0000-0000", "pin_code": "1234"},
    )
    assert resp1.status_code == 200

    resp2 = client.post(
        "/api/v1/users/set-initial-pin",
        json={"member_code": "M-8823", "phone_number": "090-0000-0000", "pin_code": "5678"},
    )
    assert resp2.status_code == 409


# --- ログイン(会員コード / 電話番号どちらでも) ---

def test_login_with_member_code():
    client.post(
        "/api/v1/users/set-initial-pin",
        json={"member_code": "M-8823", "phone_number": "090-0000-0000", "pin_code": "1234"},
    )
    resp = client.post("/api/v1/users/login", json={"identifier": "M-8823", "pin_code": "1234"})
    assert resp.status_code == 200


def test_login_with_phone_number():
    client.post(
        "/api/v1/users/set-initial-pin",
        json={"member_code": "M-8823", "phone_number": "090-0000-0000", "pin_code": "1234"},
    )
    resp = client.post("/api/v1/users/login", json={"identifier": "090-0000-0000", "pin_code": "1234"})
    assert resp.status_code == 200


def test_login_wrong_pin_rejected():
    client.post(
        "/api/v1/users/set-initial-pin",
        json={"member_code": "M-8823", "phone_number": "090-0000-0000", "pin_code": "1234"},
    )
    resp = client.post("/api/v1/users/login", json={"identifier": "M-8823", "pin_code": "0000"})
    assert resp.status_code == 401


def test_login_before_pin_set_rejected():
    resp = client.post("/api/v1/users/login", json={"identifier": "M-8823", "pin_code": "1234"})
    assert resp.status_code == 401


def test_login_lockout_after_5_failures():
    client.post(
        "/api/v1/users/set-initial-pin",
        json={"member_code": "M-8823", "phone_number": "090-0000-0000", "pin_code": "1234"},
    )
    for _ in range(5):
        resp = client.post("/api/v1/users/login", json={"identifier": "M-8823", "pin_code": "0000"})
        assert resp.status_code == 401

    # 6回目は正しいPINでもロック中なので401
    resp_locked = client.post("/api/v1/users/login", json={"identifier": "M-8823", "pin_code": "1234"})
    assert resp_locked.status_code == 401


# --- 認可:ギアセルフ登録が本人固定になっていること ---

def _member_token(member_code="M-8823", phone="090-0000-0000", pin="1234"):
    resp = client.post(
        "/api/v1/users/set-initial-pin",
        json={"member_code": member_code, "phone_number": phone, "pin_code": pin},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_gear_self_registration_requires_member_token():
    resp = client.post("/api/v1/gears", json={"gear_type": "ball", "name": "Test Ball"})
    assert resp.status_code == 401


def test_gear_self_registration_ignores_any_user_id_and_uses_token_owner():
    token = _member_token()
    headers = {"Authorization": f"Bearer {token}"}
    # GearSelfCreateスキーマにはuser_idフィールド自体が存在しないため、
    # なりすまし登録が構造的に不可能であることを確認する
    resp = client.post(
        "/api/v1/gears",
        json={"gear_type": "ball", "name": "Test Ball", "weight_or_size": "15lb"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["user_id"] == MEMBER_ID


# --- 認可:ダッシュボードはスタッフまたは本人のみ ---

def test_dashboard_accessible_by_staff():
    headers = admin_headers()
    resp = client.get(f"/api/v1/dashboard/member/{MEMBER_ID}", headers=headers)
    assert resp.status_code == 200


def test_dashboard_accessible_by_self():
    token = _member_token()
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get(f"/api/v1/dashboard/member/{MEMBER_ID}", headers=headers)
    assert resp.status_code == 200


def test_dashboard_not_accessible_by_other_member():
    token = _member_token()  # MEMBER_IDのトークン
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get(f"/api/v1/dashboard/member/{OTHER_MEMBER_ID}", headers=headers)
    assert resp.status_code == 403


def test_dashboard_requires_authentication():
    resp = client.get(f"/api/v1/dashboard/member/{MEMBER_ID}")
    assert resp.status_code == 401


# --- PIN変更 ---

def test_update_own_pin_and_relogin():
    token = _member_token()
    headers = {"Authorization": f"Bearer {token}"}

    resp_change = client.patch(
        "/api/v1/users/me/pin",
        json={"current_pin": "1234", "new_pin": "5678"},
        headers=headers,
    )
    assert resp_change.status_code == 200

    resp_old_login = client.post("/api/v1/users/login", json={"identifier": "M-8823", "pin_code": "1234"})
    assert resp_old_login.status_code == 401

    resp_new_login = client.post("/api/v1/users/login", json={"identifier": "M-8823", "pin_code": "5678"})
    assert resp_new_login.status_code == 200


# --- 会員トークンではスタッフ専用APIを使えないこと ---

def test_member_token_cannot_access_staff_only_endpoint():
    token = _member_token()
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/staff", headers=headers)
    assert resp.status_code == 401


def test_staff_token_cannot_be_used_as_member_token():
    headers = admin_headers()
    resp = client.get("/api/v1/gears/me", headers=headers)
    assert resp.status_code == 401


def test_get_my_profile_route_not_shadowed_by_user_id_route():
    """'/me' が '/{user_id}' に奪われて422になるルーティング順バグの再発防止"""
    token = _member_token()
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/users/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == MEMBER_ID
