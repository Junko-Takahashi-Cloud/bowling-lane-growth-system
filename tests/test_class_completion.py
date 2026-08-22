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
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def member_headers(member_code="M-8823", phone="090-0000-0000", pin="1234"):
    resp = client.post(
        "/api/v1/users/set-initial-pin",
        json={"member_code": member_code, "phone_number": phone, "pin_code": pin},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_record_completion_requires_staff():
    resp = client.post(
        "/api/v1/class-completions",
        json={"user_id": MEMBER_ID, "external_course_id": 101},
    )
    assert resp.status_code == 401


def test_record_completion_success():
    headers = admin_headers()
    resp = client.post(
        "/api/v1/class-completions",
        json={"user_id": MEMBER_ID, "external_course_id": 101},
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["user_id"] == MEMBER_ID
    assert data["external_course_id"] == 101
    assert data["recorded_by_staff_id"] == ADMIN_ID
    # 出席回数・指導内容・適性評価に相当するフィールドが存在しないこと（設計方針の確認）
    assert set(data.keys()) == {"id", "user_id", "external_course_id", "completed_at", "recorded_by_staff_id"}


def test_record_completion_unknown_user_404():
    headers = admin_headers()
    resp = client.post(
        "/api/v1/class-completions",
        json={"user_id": 99999, "external_course_id": 101},
        headers=headers,
    )
    assert resp.status_code == 404


def test_record_completion_does_not_validate_external_course_id():
    """external_course_idは第三弾側の値であり、本アプリのDBには存在しないため、
    存在確認をしない（＝どんな整数値でも受け付ける）ことを確認する。"""
    headers = admin_headers()
    resp = client.post(
        "/api/v1/class-completions",
        json={"user_id": MEMBER_ID, "external_course_id": 999999},
        headers=headers,
    )
    assert resp.status_code == 201


def test_list_completions_by_staff():
    headers = admin_headers()
    client.post(
        "/api/v1/class-completions", json={"user_id": MEMBER_ID, "external_course_id": 101}, headers=headers
    )
    client.post(
        "/api/v1/class-completions", json={"user_id": MEMBER_ID, "external_course_id": 202}, headers=headers
    )

    resp = client.get(f"/api/v1/class-completions/user/{MEMBER_ID}", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_completions_by_self():
    headers_admin = admin_headers()
    client.post(
        "/api/v1/class-completions", json={"user_id": MEMBER_ID, "external_course_id": 101}, headers=headers_admin
    )

    headers_member = member_headers()
    resp = client.get(f"/api/v1/class-completions/user/{MEMBER_ID}", headers=headers_member)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_completions_forbidden_for_other_member():
    headers_admin = admin_headers()
    client.post(
        "/api/v1/class-completions", json={"user_id": MEMBER_ID, "external_course_id": 101}, headers=headers_admin
    )

    headers_other = member_headers(member_code="M-9999", phone="090-9999-9999", pin="5678")
    resp = client.get(f"/api/v1/class-completions/user/{MEMBER_ID}", headers=headers_other)
    assert resp.status_code == 403


def test_list_completions_requires_authentication():
    resp = client.get(f"/api/v1/class-completions/user/{MEMBER_ID}")
    assert resp.status_code == 401
