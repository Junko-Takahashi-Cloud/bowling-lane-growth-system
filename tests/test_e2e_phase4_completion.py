import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.models import Staff, User, Gear, BowlingSession, SessionPlayer
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

    global ADMIN_ID, MEMBER_ID
    ADMIN_ID = admin.staff_id
    MEMBER_ID = member.id

    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def admin_headers():
    resp = client.post("/api/v1/staff/login", json={"staff_id": ADMIN_ID, "pin_code": "00001111"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def member_headers(member_code="M-8823", phone="090-0000-0000", pin="1234"):
    """会員本人の認証ヘッダーを返す。PIN未設定なら初回設定してからログインする。"""
    resp_set = client.post(
        "/api/v1/users/set-initial-pin",
        json={"member_code": member_code, "phone_number": phone, "pin_code": pin},
    )
    if resp_set.status_code == 200:
        token = resp_set.json()["access_token"]
    else:
        resp_login = client.post("/api/v1/users/login", json={"identifier": member_code, "pin_code": pin})
        assert resp_login.status_code == 200
        token = resp_login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# --- ③会員管理API ---

def test_create_and_get_user():
    headers = admin_headers()
    resp = client.post(
        "/api/v1/users",
        json={"member_code": "M-9001", "name": "田中太郎", "phone_number": "090-1111-2222"},
        headers=headers,
    )
    assert resp.status_code == 201
    user_id = resp.json()["id"]

    resp_get = client.get(f"/api/v1/users/{user_id}", headers=headers)
    assert resp_get.status_code == 200
    assert resp_get.json()["member_code"] == "M-9001"


def test_create_user_duplicate_member_code_rejected():
    headers = admin_headers()
    resp = client.post(
        "/api/v1/users",
        json={"member_code": "M-8823", "name": "重複太郎", "phone_number": "090-0000-0001"},
        headers=headers,
    )
    assert resp.status_code == 409


def test_create_user_requires_auth():
    resp = client.post(
        "/api/v1/users",
        json={"member_code": "M-9002", "name": "無認証太郎", "phone_number": "090-0000-0002"},
    )
    assert resp.status_code == 401


# --- ②マイギア管理API ---

def test_register_gear_self_route_requires_member_auth():
    resp_no_auth = client.post(
        "/api/v1/gears",
        json={"gear_type": "ball", "name": "Storm Phaze II", "weight_or_size": "15lb"},
    )
    assert resp_no_auth.status_code == 401


def test_register_gear_self_route_registers_to_own_account_only():
    headers = member_headers()
    resp = client.post(
        "/api/v1/gears",
        json={"gear_type": "ball", "name": "Storm Phaze II", "weight_or_size": "15lb"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["user_id"] == MEMBER_ID
    assert resp.json()["total_games"] == 0


def test_register_gear_by_staff_route_requires_auth():
    resp_no_auth = client.post(
        "/api/v1/gears/by-staff",
        json={"user_id": MEMBER_ID, "gear_type": "shoes", "name": "Dexter SST8", "weight_or_size": "26.5cm"},
    )
    assert resp_no_auth.status_code == 401

    headers = admin_headers()
    resp = client.post(
        "/api/v1/gears/by-staff",
        json={"user_id": MEMBER_ID, "gear_type": "shoes", "name": "Dexter SST8", "weight_or_size": "26.5cm"},
        headers=headers,
    )
    assert resp.status_code == 201


def test_register_gear_by_staff_unknown_user_returns_404():
    headers = admin_headers()
    resp = client.post(
        "/api/v1/gears/by-staff",
        json={"user_id": 99999, "gear_type": "ball", "name": "存在しない会員用", "weight_or_size": "15lb"},
        headers=headers,
    )
    assert resp.status_code == 404


def test_list_gears_for_user():
    headers_admin = admin_headers()
    client.post(
        "/api/v1/gears/by-staff",
        json={"user_id": MEMBER_ID, "gear_type": "ball", "name": "Roto Grip Idol", "weight_or_size": "15lb"},
        headers=headers_admin,
    )
    headers = admin_headers()
    resp = client.get(f"/api/v1/gears/user/{MEMBER_ID}", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


# --- ①複数人セッションAPI ---

def test_add_second_player_to_existing_session():
    headers = admin_headers()
    resp_checkin = client.post(
        "/api/v1/checkin", data={"lane_number": 5, "member_code": "M-8823"}, headers=headers
    )
    assert resp_checkin.status_code == 200
    session_id = resp_checkin.json()["session_id"]

    resp_add = client.post(
        f"/api/v1/sessions/{session_id}/players",
        json={"guest_name": "同行者ゲスト"},
        headers=headers,
    )
    assert resp_add.status_code == 201
    assert resp_add.json()["player_order"] == 2

    resp_list = client.get(f"/api/v1/sessions/{session_id}/players", headers=headers)
    assert resp_list.status_code == 200
    assert len(resp_list.json()) == 2


def test_add_player_to_completed_session_rejected():
    headers = admin_headers()
    resp_checkin = client.post("/api/v1/checkin", data={"lane_number": 6, "guest_name": "1人目"}, headers=headers)
    session_id = resp_checkin.json()["session_id"]
    client.post(f"/api/v1/checkout/{session_id}", headers=headers)

    resp_add = client.post(
        f"/api/v1/sessions/{session_id}/players",
        json={"guest_name": "後から追加"},
        headers=headers,
    )
    assert resp_add.status_code == 400


# --- ⑤Frame/Shot実データ投入 + ④Gear紐付け ---

def _standard_192_frames():
    return [
        {"frame_number": 1, "shots": [{"pins_knocked": 10}]},
        {"frame_number": 2, "shots": [{"pins_knocked": 7}, {"pins_knocked": 3}]},
        {"frame_number": 3, "shots": [{"pins_knocked": 7, "remaining_pins": "3"}, {"pins_knocked": 2}]},
        {"frame_number": 4, "shots": [{"pins_knocked": 10}]},
        {"frame_number": 5, "shots": [{"pins_knocked": 10}]},
        {"frame_number": 6, "shots": [{"pins_knocked": 10}]},
        {"frame_number": 7, "shots": [{"pins_knocked": 8, "remaining_pins": "10"}, {"pins_knocked": 1}]},
        {"frame_number": 8, "shots": [{"pins_knocked": 0}, {"pins_knocked": 9}]},
        {"frame_number": 9, "shots": [{"pins_knocked": 10}]},
        {"frame_number": 10, "shots": [{"pins_knocked": 10}, {"pins_knocked": 10}, {"pins_knocked": 1}]},
    ]


def test_import_scores_with_gear_and_dashboard_reflects_it():
    headers = admin_headers()

    resp_checkin = client.post("/api/v1/checkin", data={"lane_number": 4, "member_code": "M-8823"}, headers=headers)
    session_id = resp_checkin.json()["session_id"]
    resp_players = client.get(f"/api/v1/sessions/{session_id}/players", headers=headers)
    player_id = resp_players.json()[0]["id"]

    resp_gear = client.post(
        "/api/v1/gears/by-staff",
        json={"user_id": MEMBER_ID, "gear_type": "ball", "name": "Storm Phaze II", "weight_or_size": "15lb"},
        headers=headers,
    )
    gear_id = resp_gear.json()["id"]

    payload = {
        "games": [
            {
                "player_id": player_id,
                "gear_id": gear_id,
                "game_number": 1,
                "frames": _standard_192_frames(),
            }
        ]
    }
    resp_import = client.post("/api/v1/scores/import", json=payload, headers=headers)
    assert resp_import.status_code == 200
    result = resp_import.json()
    assert result["imported_games"][0]["total_score"] == 192

    # ④Gear紐付け：使用ギアの累計ゲーム数が1増えている
    resp_gear_list = client.get(f"/api/v1/gears/user/{MEMBER_ID}", headers=headers)
    matched = [g for g in resp_gear_list.json() if g["id"] == gear_id][0]
    assert matched["total_games"] == 1

    # ⑥成長ダッシュボードに反映されている
    resp_dash = client.get(f"/api/v1/dashboard/member/{MEMBER_ID}", headers=headers)
    assert resp_dash.status_code == 200
    dash = resp_dash.json()
    assert dash["total_games"] == 1
    assert dash["average_score"] == 192.0
    assert dash["high_score"] == 192
    assert dash["strike_rate"] > 0
    assert dash["spare_rate"] > 0
    assert dash["pin10_leave_rate"] > 0  # F3, F7で10番ピン残りを記録している
    assert len(dash["recent_games"]) == 1


def test_import_scores_unknown_player_returns_404():
    headers = admin_headers()
    payload = {
        "games": [
            {"player_id": 99999, "game_number": 1, "frames": _standard_192_frames()}
        ]
    }
    resp = client.post("/api/v1/scores/import", json=payload, headers=headers)
    assert resp.status_code == 404


def test_import_scores_unknown_gear_returns_404():
    headers = admin_headers()
    resp_checkin = client.post("/api/v1/checkin", data={"lane_number": 7, "member_code": "M-8823"}, headers=headers)
    session_id = resp_checkin.json()["session_id"]
    player_id = client.get(f"/api/v1/sessions/{session_id}/players", headers=headers).json()[0]["id"]

    payload = {
        "games": [
            {"player_id": player_id, "gear_id": 99999, "game_number": 1, "frames": _standard_192_frames()}
        ]
    }
    resp = client.post("/api/v1/scores/import", json=payload, headers=headers)
    assert resp.status_code == 404


# --- ⑥成長ダッシュボード：データなし会員 ---

def test_dashboard_for_member_with_no_games_returns_zeros():
    headers = admin_headers()
    resp = client.get(f"/api/v1/dashboard/member/{MEMBER_ID}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_games"] == 0
    assert data["average_score"] == 0.0
    assert data["recent_games"] == []


def test_dashboard_unknown_user_returns_404():
    headers = admin_headers()
    resp = client.get("/api/v1/dashboard/member/99999", headers=headers)
    assert resp.status_code == 404
