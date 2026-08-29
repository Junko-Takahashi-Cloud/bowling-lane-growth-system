"""
バッジ・称号の判定ロジック（第三弾拡張③）。

設計方針：
- badge_codeごとに「achieved(user_id, db) -> bool」という判定関数を1つ登録する
- 第四弾単体で完結する条件のみを初期実装とし、第五弾の分析指標(ストライク率等)への
  依存は持たせない。将来、第五弾の指標を使う判定を追加したくなった場合は、
  ここに新しい判定関数を追加するだけで済む構造にしておく（③自体は「評価して
  付与できる仕組み」が中心であり、判定条件の充実は将来の拡張候補）。
"""
from typing import Callable, Dict
from sqlalchemy.orm import Session
from app.models import Game, SessionPlayer, Gear

BadgeCriterion = Callable[[int, Session], bool]


def _has_played_first_game(user_id: int, db: Session) -> bool:
    player_ids = [p.id for p in db.query(SessionPlayer).filter(SessionPlayer.user_id == user_id).all()]
    if not player_ids:
        return False
    return db.query(Game).filter(Game.player_id.in_(player_ids)).first() is not None


def _has_played_10_games(user_id: int, db: Session) -> bool:
    player_ids = [p.id for p in db.query(SessionPlayer).filter(SessionPlayer.user_id == user_id).all()]
    if not player_ids:
        return False
    count = db.query(Game).filter(Game.player_id.in_(player_ids)).count()
    return count >= 10


def _has_played_100_games(user_id: int, db: Session) -> bool:
    player_ids = [p.id for p in db.query(SessionPlayer).filter(SessionPlayer.user_id == user_id).all()]
    if not player_ids:
        return False
    count = db.query(Game).filter(Game.player_id.in_(player_ids)).count()
    return count >= 100


def _has_registered_gear(user_id: int, db: Session) -> bool:
    return db.query(Gear).filter(Gear.user_id == user_id).first() is not None


# badge_code -> (表示名, 判定関数)
BADGE_CRITERIA: Dict[str, "tuple[str, BadgeCriterion]"] = {
    "first_game": ("初投球", _has_played_first_game),
    "ten_games": ("累計10ゲーム達成", _has_played_10_games),
    "hundred_games": ("累計100ゲーム達成", _has_played_100_games),
    "gear_registered": ("マイギア登録", _has_registered_gear),
}
