"""
api/index.py
============
Flask Serverless API (Vercel) cho Enigma Card.

Endpoints:
    POST /api/game/start      - Khởi tạo trận (KHÔNG trả bot_hand / SB)
    POST /api/game/bot-turn   - Bot ra quyết định FOLD / CALL / RAISE
    POST /api/game/showdown   - Kết thúc trận, lộ bài Bot, tính Pot + Elo
"""

import os
import sys
import time
import uuid
import threading

from flask import Flask, jsonify, request

# Cho phép import `modules.*` khi chạy trên Vercel (thư mục gốc dự án)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.game_engine import EnigmaEngine  # noqa: E402

app = Flask(__name__)

# ----------------------------------------------------------------------
# BỘ NHỚ TRẬN ĐẤU PHÍA SERVER
# LƯU Ý: Vercel Serverless có thể tạo nhiều instance, RAM không chia sẻ
# giữa các instance. Với production hãy thay GameStore bằng Redis /
# Vercel KV (giữ nguyên interface get/set).
# ----------------------------------------------------------------------
class GameStore:
    TTL_SECONDS = 30 * 60   # trận quá 30 phút sẽ bị dọn
    MAX_GAMES = 2000        # giới hạn tránh phình RAM

    def __init__(self):
        self._games = {}
        self._lock = threading.Lock()

    def _cleanup(self):
        now = time.time()
        expired = [k for k, v in self._games.items() if now - v["created_at"] > self.TTL_SECONDS]
        for k in expired:
            del self._games[k]
        # Nếu vẫn vượt giới hạn, xóa các trận cũ nhất
        if len(self._games) >= self.MAX_GAMES:
            oldest = sorted(self._games.items(), key=lambda kv: kv[1]["created_at"])
            for k, _ in oldest[: len(self._games) - self.MAX_GAMES + 1]:
                del self._games[k]

    def create(self, state: dict) -> str:
        with self._lock:
            self._cleanup()
            game_id = uuid.uuid4().hex
            state["created_at"] = time.time()
            self._games[game_id] = state
            return game_id

    def get(self, game_id):
        with self._lock:
            return self._games.get(game_id)


STORE = GameStore()


# ----------------------------------------------------------------------
# HÀM TIỆN ÍCH
# ----------------------------------------------------------------------
def error(message: str, status: int):
    return jsonify({"success": False, "error": message}), status


def to_int(value, default: int, minimum: int = 0, maximum: int = 10_000) -> int:
    """Ép kiểu int an toàn, kẹp trong [minimum, maximum]."""
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def load_game(data: dict):
    """Lấy trận theo game_id. Trả về (game, None) hoặc (None, response_lỗi)."""
    game_id = data.get("game_id")
    if not game_id or not isinstance(game_id, str):
        return None, error("Thiếu game_id", 400)
    game = STORE.get(game_id)
    if game is None:
        return None, error("game_id không tồn tại hoặc đã hết hạn", 404)
    return game, None


# ----------------------------------------------------------------------
# ROUTES
# ----------------------------------------------------------------------
@app.route("/api/game/start", methods=["POST"])
def start_game():
    try:
        data = request.get_json(silent=True) or {}
        mode = EnigmaEngine.normalize_mode(data.get("mode", "AI"))
        bot_elo = to_int(data.get("bot_elo"), default=1000)

        match = EnigmaEngine.generate_match(mode)

        # Toàn bộ trạng thái (kể cả bot_hand, SB) chỉ nằm ở server
        game_id = STORE.create({
            "mode": mode,
            "bot_elo": bot_elo,
            "player_hand": match["player_hand"],
            "bot_hand": match["bot_hand"],
            "SA": match["SA"],
            "SB": match["SB"],
            "board_cards": match["board_cards"],
            "mystery_value": match["mystery_value"],
            "pot": match["pot"],
            "bot_action": None,
            "bot_is_bluff": False,
            "finished": False,
            "result_cache": None,
        })

        # TUYỆT ĐỐI không trả bot_hand / SB
        return jsonify({
            "success": True,
            "game_id": game_id,
            "mode": mode,
            "player_hand": match["player_hand"],
            "board_cards": match["board_cards"],
            "mystery_value": match["mystery_value"],
            "pot": match["pot"],
        }), 200

    except ValueError as exc:  # mode sai
        return error(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("start_game failed")
        return error(f"Lỗi server: {exc}", 500)


@app.route("/api/game/bot-turn", methods=["POST"])
def bot_turn():
    try:
        data = request.get_json(silent=True) or {}
        game, err = load_game(data)
        if err:
            return err

        if game["finished"]:
            return error("Trận đấu đã kết thúc", 409)
        if game["bot_action"] is not None:
            return error("Bot đã hành động trong ván này", 409)

        decision = EnigmaEngine.advanced_bot_decision(
            sb=game["SB"],
            board=game["board_cards"],
            mystery_value=game["mystery_value"],
            bot_elo=game["bot_elo"],
            mode=game["mode"],
            pot=game["pot"],
        )

        # Cập nhật Pot nếu Bot tố
        if decision["action"] == "RAISE":
            game["pot"] += decision["raise_amount"]

        game["bot_action"] = decision["action"]
        game["bot_is_bluff"] = decision["is_bluff"]  # chỉ lộ ở showdown

        # Không trả estimated_sa / is_bluff / lý do để tránh lộ thông tin
        return jsonify({
            "success": True,
            "action": decision["action"],
            "raise_amount": decision["raise_amount"],
            "pot": game["pot"],
        }), 200

    except Exception as exc:  # noqa: BLE001
        app.logger.exception("bot_turn failed")
        return error(f"Lỗi server: {exc}", 500)


@app.route("/api/game/showdown", methods=["POST"])
def showdown():
    try:
        data = request.get_json(silent=True) or {}
        game, err = load_game(data)
        if err:
            return err

        # Idempotent: gọi lại không cộng/trừ Elo lần 2
        if game["finished"] and game["result_cache"]:
            return jsonify(game["result_cache"]), 200

        if game["bot_action"] is None:
            return error("Bot chưa hành động, hãy gọi /api/game/bot-turn trước", 409)

        player_action = str(data.get("player_action", "CALL")).upper()
        if player_action not in ("CALL", "FOLD"):
            return error("player_action chỉ nhận 'CALL' hoặc 'FOLD'", 400)

        player_elo = to_int(data.get("player_elo"), default=1000)

        outcome = EnigmaEngine.evaluate_match(
            sa=game["SA"],
            sb=game["SB"],
            mode=game["mode"],
            pot=game["pot"],
            player_elo=player_elo,
            player_folded=(player_action == "FOLD"),
            bot_folded=(game["bot_action"] == "FOLD"),
        )

        payload = {
            "success": True,
            "game_id": data["game_id"],
            "result": outcome["result"],
            "bot_hand": game["bot_hand"],           # giờ mới được lộ
            "player_hand": game["player_hand"],
            "player_score": game["SA"],
            "bot_score": game["SB"],
            "bot_action": game["bot_action"],
            "bot_bluffed": game["bot_is_bluff"],
            "pot": game["pot"],
            "pot_won": outcome["pot_won"],
            "elo_change": outcome["elo_change"],
            "new_player_elo": outcome["new_player_elo"],
        }

        game["finished"] = True
        game["result_cache"] = payload
        return jsonify(payload), 200

    except Exception as exc:  # noqa: BLE001
        app.logger.exception("showdown failed")
        return error(f"Lỗi server: {exc}", 500)


# Chạy local: python api/index.py  (Vercel tự dùng biến `app`)
if __name__ == "__main__":
    app.run(debug=True, port=5056)