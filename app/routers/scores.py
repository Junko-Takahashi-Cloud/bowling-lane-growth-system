from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Game, Frame, Shot, SessionPlayer, Gear, Staff
from app.schemas import ScoreImportRequest, ScoreImportResponse, GameImportResult
from app.utils.staff_auth import get_current_staff
from app.services.score_calculator import calculate_bowling_score

router = APIRouter(prefix="/api/v1/scores", tags=["scores"])


@router.post("/import", response_model=ScoreImportResponse)
def import_scores(
    request: ScoreImportRequest,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    """閉店時、オートスコアラーCSVを一括取込む想定のAPI。
    レーン番号・時間帯からplayer_id（SessionPlayer.id）を特定するマッチング処理自体は、
    CSVパース層で行われる前提とし、本APIはplayer_id特定後のデータ投入を担う。"""
    results: list[GameImportResult] = []

    for game_input in request.games:
        player = db.query(SessionPlayer).filter(SessionPlayer.id == game_input.player_id).first()
        if not player:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"player_id={game_input.player_id} のプレイヤーが見つかりません",
            )

        gear = None
        if game_input.gear_id is not None:
            gear = db.query(Gear).filter(Gear.id == game_input.gear_id).first()
            if not gear:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"gear_id={game_input.gear_id} のギアが見つかりません",
                )

        frames_data = [
            {"frame_number": f.frame_number, "shots": [s.pins_knocked for s in f.shots]}
            for f in game_input.frames
        ]
        total_score, frame_cumulative_scores = calculate_bowling_score(frames_data)

        game = Game(
            player_id=game_input.player_id,
            gear_id=game_input.gear_id,
            game_number=game_input.game_number,
            total_score=total_score,
        )
        db.add(game)
        db.flush()

        sorted_frames = sorted(game_input.frames, key=lambda f: f.frame_number)
        for f_idx, f_input in enumerate(sorted_frames):
            frame_obj = Frame(
                game_id=game.id,
                frame_number=f_input.frame_number,
                score=frame_cumulative_scores[f_idx],
            )
            db.add(frame_obj)
            db.flush()

            for s_idx, shot_input in enumerate(f_input.shots, start=1):
                shot_obj = Shot(
                    frame_id=frame_obj.id,
                    shot_number=s_idx,
                    pins_knocked=shot_input.pins_knocked,
                    remaining_pins=shot_input.remaining_pins,
                )
                db.add(shot_obj)

        # ④Gear⇔Game紐付け：使用ギアが指定されていれば累計ゲーム数をカウント
        if gear is not None:
            gear.total_games = (gear.total_games or 0) + 1

        db.commit()
        db.refresh(game)

        results.append(GameImportResult(game_id=game.id, player_id=game.player_id, total_score=game.total_score))

    return ScoreImportResponse(
        imported_games=results,
        message=f"{len(results)}件のゲームデータを取り込みました",
    )
