"""
modules/game_engine.py
======================
Enigma Card - Core Engine (thuần logic, không phụ thuộc Flask).

Chứa class EnigmaEngine với 3 thuật toán chính:
    1. generate_match()        : sinh bàn đấu (bài tẩy, bài bàn, Mystery Value, Pot)
    2. advanced_bot_decision() : AI suy luận ngược SA từ M + lý thuyết trò chơi
    3. evaluate_match()        : Showdown, tính thắng/thua/hòa, Pot và biến động Elo
"""

import math
import random
from typing import Dict, List, Optional


class EnigmaEngine:
    # ------------------------------------------------------------------
    # HẰNG SỐ CẤU HÌNH
    # ------------------------------------------------------------------
    CARD_MIN = 1                 # Giá trị lá bài nhỏ nhất
    CARD_MAX = 10                # Giá trị lá bài lớn nhất
    BOARD_SIZE = 5               # Số lá bài trên bàn (X, Y, Z, ...)

    BASE_POT = 200               # Pot khởi điểm chế độ thường
    EXTREME_POT_MULTIPLIER = 2   # EXTREME: Pot x2 => 400

    BOSS_ELO = 2000              # Elo >= 2000 => Boss AI
    BLUFF_CHANCE = 0.20          # 20% bluff khi SB < estimated_SA
    RAISE_RATIO = 0.25           # Mỗi lần Tố = 25% Pot hiện tại

    # Ngưỡng quyết định của Bot thường (Elo < 2000), dựa trên SB (2..20)
    WEAK_BOT_RAISE_MIN = 14      # SB >= 14 -> RAISE
    WEAK_BOT_CALL_MIN = 9        # 9 <= SB < 14 -> CALL, còn lại FOLD

    # Điểm Elo thưởng/phạt: PvP +25/-20, AI +15/-10 (EXTREME dùng bảng AI)
    ELO_RULES = {
        "PVP": {"win": 25, "lose": -20},
        "AI": {"win": 15, "lose": -10},
    }

    VALID_MODES = ("AI", "PVP", "EXTREME")

    # ------------------------------------------------------------------
    # TIỆN ÍCH
    # ------------------------------------------------------------------
    @classmethod
    def normalize_mode(cls, mode: Optional[str]) -> str:
        """Chuẩn hóa mode về chữ HOA; 'NORMAL'/'THUONG' được coi là 'AI'."""
        m = str(mode or "AI").strip().upper()
        if m in ("NORMAL", "THUONG", "THƯỜNG"):
            m = "AI"
        if m not in cls.VALID_MODES:
            raise ValueError(f"Mode không hợp lệ: '{mode}'. Hợp lệ: {cls.VALID_MODES}")
        return m

    @classmethod
    def _draw_hand(cls, rng: random.Random) -> List[int]:
        """Rút 2 lá bài tẩy ngẫu nhiên trong khoảng 1..10."""
        return [rng.randint(cls.CARD_MIN, cls.CARD_MAX) for _ in range(2)]

    @classmethod
    def calculate_mystery_value(cls, mode: str, sa: int, sb: int, board: List[int]) -> int:
        """
        Tính Mystery Value M theo chế độ:
            - AI / PVP : M = (SA + SB) * X
            - EXTREME  : M = (SA * X) + (SB * Y) - Z
        Với X, Y, Z lần lượt là lá bài bàn thứ 1, 2, 3.
        """
        x, y, z = board[0], board[1], board[2]
        if mode == "EXTREME":
            return (sa * x) + (sb * y) - z
        return (sa + sb) * x

    # ------------------------------------------------------------------
    # 1. TẠO BÀN ĐẤU
    # ------------------------------------------------------------------
    @classmethod
    def generate_match(cls, mode: str = "AI", rng: Optional[random.Random] = None) -> Dict:
        """
        Sinh một bàn đấu hoàn chỉnh.
        Trả về dict (CHỨA bot_hand - tầng API tuyệt đối không được gửi cho client).
        """
        mode = cls.normalize_mode(mode)
        rng = rng or random.Random()

        player_hand = cls._draw_hand(rng)
        bot_hand = cls._draw_hand(rng)
        board = [rng.randint(cls.CARD_MIN, cls.CARD_MAX) for _ in range(cls.BOARD_SIZE)]

        sa = sum(player_hand)
        sb = sum(bot_hand)
        mystery_value = cls.calculate_mystery_value(mode, sa, sb, board)

        pot = cls.BASE_POT * (cls.EXTREME_POT_MULTIPLIER if mode == "EXTREME" else 1)

        return {
            "mode": mode,
            "player_hand": player_hand,
            "bot_hand": bot_hand,
            "SA": sa,
            "SB": sb,
            "board_cards": board,
            "mystery_value": mystery_value,
            "pot": pot,
        }

    # ------------------------------------------------------------------
    # 2. AI SUY LUẬN & LÝ THUYẾT TRÒ CHƠI
    # ------------------------------------------------------------------
    @classmethod
    def estimate_player_score(cls, sb: int, board: List[int], mystery_value: int,
                              mode: str = "AI") -> float:
        """
        Suy ngược SA từ M (Bot biết SB của chính nó + bài bàn + M).
            - AI / PVP : estimated_SA = (M / X) - SB
            - EXTREME  : từ M = SA*X + SB*Y - Z  =>  estimated_SA = (M - SB*Y + Z) / X
        X luôn >= 1 nên không có chia cho 0.
        """
        x, y, z = board[0], board[1], board[2]
        if mode == "EXTREME":
            return (mystery_value - sb * y + z) / x
        return (mystery_value / x) - sb

    @classmethod
    def calculate_raise_amount(cls, pot: int) -> int:
        """Số điểm Bot tố thêm = 25% Pot hiện tại (tối thiểu 10)."""
        return max(10, int(pot * cls.RAISE_RATIO))

    @classmethod
    def advanced_bot_decision(cls, sb: int, board: List[int], mystery_value: int,
                              bot_elo: int, mode: str = "AI", pot: Optional[int] = None,
                              rng: Optional[random.Random] = None) -> Dict:
        """
        Bot quyết định FOLD / CALL / RAISE.

        - Elo >= 2000 (Boss): suy ngược estimated_SA rồi
              SB >  estimated_SA -> RAISE
              SB == estimated_SA -> CALL
              SB <  estimated_SA -> 20% BLUFF (RAISE phỉnh), 80% FOLD
        - Elo <  2000: quyết định theo mốc SB cố định.

        Trả về dict: action, raise_amount, estimated_sa, is_bluff, reason
        """
        rng = rng or random.Random()
        mode = cls.normalize_mode(mode)
        pot = pot if pot is not None else cls.BASE_POT
        estimated_sa = cls.estimate_player_score(sb, board, mystery_value, mode)

        action = "FOLD"
        is_bluff = False
        reason = ""

        if bot_elo >= cls.BOSS_ELO:
            # So sánh số thực bằng math.isclose để tránh lỗi làm tròn
            if math.isclose(sb, estimated_sa, abs_tol=1e-9):
                action, reason = "CALL", "Boss: SB bằng SA ước lượng -> Theo"
            elif sb > estimated_sa:
                action, reason = "RAISE", "Boss: SB lớn hơn SA ước lượng -> Tố"
            else:
                if rng.random() < cls.BLUFF_CHANCE:
                    action, is_bluff = "RAISE", True
                    reason = "Boss: SB yếu hơn nhưng Bluff dọa người chơi"
                else:
                    action, reason = "FOLD", "Boss: SB yếu hơn -> Bỏ bài"
        else:
            if sb >= cls.WEAK_BOT_RAISE_MIN:
                action, reason = "RAISE", "Bot thường: SB mạnh -> Tố"
            elif sb >= cls.WEAK_BOT_CALL_MIN:
                action, reason = "CALL", "Bot thường: SB trung bình -> Theo"
            else:
                action, reason = "FOLD", "Bot thường: SB yếu -> Bỏ bài"

        raise_amount = cls.calculate_raise_amount(pot) if action == "RAISE" else 0

        return {
            "action": action,
            "raise_amount": raise_amount,
            "estimated_sa": estimated_sa,
            "is_bluff": is_bluff,
            "reason": reason,
        }

    # ------------------------------------------------------------------
    # 3. SHOWDOWN & ELO
    # ------------------------------------------------------------------
    @classmethod
    def get_elo_delta(cls, mode: str, result: str) -> int:
        """Trả về biến động Elo theo mode và kết quả (DRAW = 0)."""
        if result == "DRAW":
            return 0
        rules = cls.ELO_RULES["PVP"] if mode == "PVP" else cls.ELO_RULES["AI"]
        return rules["win"] if result == "WIN" else rules["lose"]

    @classmethod
    def evaluate_match(cls, sa: int, sb: int, mode: str, pot: int,
                       player_elo: int = 1000,
                       player_folded: bool = False,
                       bot_folded: bool = False) -> Dict:
        """
        Xử lý Showdown.
        - Người chơi FOLD -> LOSE; Bot FOLD -> WIN (không cần so điểm).
        - Ngược lại so SA với SB.
        Pot nhận: WIN = toàn bộ Pot, DRAW = hoàn một nửa, LOSE = 0.
        """
        mode = cls.normalize_mode(mode)

        if player_folded:
            result = "LOSE"
        elif bot_folded:
            result = "WIN"
        elif sa > sb:
            result = "WIN"
        elif sa < sb:
            result = "LOSE"
        else:
            result = "DRAW"

        if result == "WIN":
            pot_won = pot
        elif result == "DRAW":
            pot_won = pot // 2
        else:
            pot_won = 0

        elo_change = cls.get_elo_delta(mode, result)
        new_elo = max(0, player_elo + elo_change)  # Elo không âm
        elo_change = new_elo - player_elo          # điều chỉnh nếu bị chặn ở 0

        return {
            "result": result,
            "pot_won": pot_won,
            "elo_change": elo_change,
            "new_player_elo": new_elo,
        }