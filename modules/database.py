"""
modules/database.py
===================
Lớp truy cập dữ liệu SQLite cho Enigma Card.

Bảng:
    users   (id, username, password_hash, elo, pvp_wins, pvp_losses)
    friends (id, user_id, friend_id, status, created_at)

Hàm chính:
    init_db()                -> tạo bảng nếu chưa có
    get_user_by_username()   -> lấy người dùng theo tên đăng nhập
    create_user()            -> tạo người dùng mới
    update_user_stats()      -> cập nhật Elo và thống kê thắng/thua PvP

LƯU Ý QUAN TRỌNG KHI DEPLOY LÊN VERCEL:
    Hệ thống file của Vercel Serverless chỉ ghi được vào thư mục /tmp và dữ
    liệu ở đó là TẠM THỜI (mất khi instance bị thu hồi). File SQLite chỉ phù
    hợp để chạy local hoặc demo. Với production hãy chuyển sang Turso (libSQL),
    Vercel Postgres hoặc một database ngoài, và giữ nguyên các hàm bên dưới.
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Dict, List, Optional

# ----------------------------------------------------------------------
# CẤU HÌNH ĐƯỜNG DẪN DATABASE
# ----------------------------------------------------------------------
DEFAULT_ELO = 1000  # Elo khởi điểm của người dùng mới


def _resolve_db_path() -> str:
    """
    Xác định đường dẫn file SQLite theo thứ tự ưu tiên:
        1. Biến môi trường ENIGMA_DB_PATH (nếu có)
        2. Trên Vercel (biến môi trường VERCEL): /tmp/enigma.db
        3. Local: <thư mục gốc dự án>/data/enigma.db
    """
    env_path = os.environ.get("ENIGMA_DB_PATH")
    if env_path:
        return env_path

    if os.environ.get("VERCEL"):
        return "/tmp/enigma.db"

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(project_root, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "enigma.db")


DB_PATH = _resolve_db_path()


# ----------------------------------------------------------------------
# KẾT NỐI
# ----------------------------------------------------------------------
@contextmanager
def get_connection():
    """
    Context manager mở kết nối SQLite.
    - Tự commit khi khối lệnh chạy thành công.
    - Tự rollback khi có ngoại lệ, sau đó ném lại ngoại lệ đó.
    - Luôn đóng kết nối ở cuối.
    - row_factory = sqlite3.Row để truy cập cột theo tên.
    - Bật PRAGMA foreign_keys để ràng buộc khóa ngoại có hiệu lực.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict]:
    """Chuyển sqlite3.Row thành dict thường (hoặc None nếu không có dòng)."""
    return dict(row) if row is not None else None


# ----------------------------------------------------------------------
# KHỞI TẠO BẢNG
# ----------------------------------------------------------------------
def init_db() -> None:
    """Tạo các bảng users và friends nếu chúng chưa tồn tại."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT    NOT NULL,
                elo           INTEGER NOT NULL DEFAULT 1000,
                pvp_wins      INTEGER NOT NULL DEFAULT 0,
                pvp_losses    INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS friends (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                friend_id  INTEGER NOT NULL,
                status     TEXT    NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending', 'accepted', 'blocked')),
                created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, friend_id),
                CHECK (user_id != friend_id),
                FOREIGN KEY (user_id)   REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (friend_id) REFERENCES users (id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_friends_user ON friends (user_id)")


# ----------------------------------------------------------------------
# NGƯỜI DÙNG
# ----------------------------------------------------------------------
def get_user_by_username(username: str) -> Optional[Dict]:
    """
    Lấy người dùng theo username (không phân biệt hoa thường).
    Trả về dict đầy đủ cột (BAO GỒM password_hash để auth.py kiểm tra mật khẩu)
    hoặc None nếu không tồn tại. Không được gửi dict này thẳng cho client.
    """
    if not username:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, elo, pvp_wins, pvp_losses "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    return _row_to_dict(row)


def get_user_by_id(user_id: int) -> Optional[Dict]:
    """Lấy người dùng theo id. Trả về None nếu không tồn tại."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, elo, pvp_wins, pvp_losses "
            "FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return _row_to_dict(row)


def create_user(username: str, password_hash: str, elo: int = DEFAULT_ELO) -> Optional[int]:
    """
    Tạo người dùng mới.
    Trả về id của người dùng vừa tạo, hoặc None nếu username đã tồn tại.
    """
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, elo) VALUES (?, ?, ?)",
                (username, password_hash, elo),
            )
            return cursor.lastrowid
    except sqlite3.IntegrityError:
        # Vi phạm ràng buộc UNIQUE của username
        return None


def update_user_stats(user_id: int, elo_change: int = 0,
                      pvp_result: Optional[str] = None) -> Optional[Dict]:
    """
    Cập nhật Elo và thống kê PvP của người dùng trong MỘT câu lệnh UPDATE
    (an toàn khi nhiều request chạy đồng thời).

    Tham số:
        user_id    : id người dùng.
        elo_change : biến động Elo (+25, -20, ...). Elo mới không bao giờ < 0.
        pvp_result : 'WIN'  -> pvp_wins   + 1
                     'LOSE' -> pvp_losses + 1
                     'DRAW' hoặc None -> không đổi bộ đếm.

    Trả về dict người dùng sau khi cập nhật, hoặc None nếu không tìm thấy user.
    Ném ValueError nếu pvp_result không hợp lệ.
    """
    result = str(pvp_result).upper() if pvp_result is not None else None
    if result not in (None, "WIN", "LOSE", "DRAW"):
        raise ValueError("pvp_result chỉ nhận 'WIN', 'LOSE', 'DRAW' hoặc None")

    win_increment = 1 if result == "WIN" else 0
    loss_increment = 1 if result == "LOSE" else 0

    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE users "
            "SET elo = MAX(0, elo + ?), "
            "    pvp_wins = pvp_wins + ?, "
            "    pvp_losses = pvp_losses + ? "
            "WHERE id = ?",
            (int(elo_change), win_increment, loss_increment, user_id),
        )
        if cursor.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT id, username, password_hash, elo, pvp_wins, pvp_losses "
            "FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return _row_to_dict(row)


# ----------------------------------------------------------------------
# BẠN BÈ
# ----------------------------------------------------------------------
def add_friend(user_id: int, friend_id: int, status: str = "pending") -> bool:
    """
    Thêm một quan hệ bạn bè (một chiều: user_id -> friend_id).
    Trả về True nếu thêm thành công, False nếu đã tồn tại, tự kết bạn với
    chính mình, hoặc một trong hai user không tồn tại.
    """
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO friends (user_id, friend_id, status) VALUES (?, ?, ?)",
                (user_id, friend_id, status),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def get_friends(user_id: int) -> List[Dict]:
    """Trả về danh sách bạn bè đã chấp nhận (id, username, elo) của user_id."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT u.id, u.username, u.elo "
            "FROM friends f JOIN users u ON u.id = f.friend_id "
            "WHERE f.user_id = ? AND f.status = 'accepted' "
            "ORDER BY u.username",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# Tự tạo bảng khi module được import lần đầu
init_db()