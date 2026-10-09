"""
modules/auth.py
===============
Xác thực người dùng cho Enigma Card, chỉ dùng thư viện chuẩn (hashlib, hmac).

Hàm chính:
    hash_password(password)           -> chuỗi băm có salt
    verify_password(password, stored) -> kiểm tra mật khẩu
    register_user(username, password) -> đăng ký
    login_user(username, password)    -> đăng nhập

Thuật toán băm: PBKDF2-HMAC-SHA256 (hashlib.pbkdf2_hmac) với salt ngẫu nhiên
cho từng người dùng. Định dạng lưu trong DB:
    pbkdf2_sha256$<số vòng lặp>$<salt hex>$<hash hex>

Module này chỉ xử lý logic. Việc cấp session/token sau khi đăng nhập thành
công do tầng API đảm nhiệm.
"""

import hashlib
import hmac
import os
import re
from typing import Dict, Optional

from modules.database import create_user, get_user_by_username

# ----------------------------------------------------------------------
# CẤU HÌNH
# ----------------------------------------------------------------------
HASH_ALGORITHM = "sha256"
PBKDF2_ITERATIONS = 200_000   # Số vòng lặp PBKDF2
SALT_BYTES = 16               # 16 byte = 128 bit salt

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,20}$")  # 3-20 ký tự chữ, số, _
MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_LENGTH = 128


# ----------------------------------------------------------------------
# BĂM MẬT KHẨU
# ----------------------------------------------------------------------
def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    """
    Băm mật khẩu bằng PBKDF2-HMAC-SHA256.

    Tham số:
        password : mật khẩu dạng văn bản thuần.
        salt     : salt dạng bytes. Nếu None, tự sinh salt ngẫu nhiên mới.
                   (Chỉ truyền salt khi cần kiểm tra lại mật khẩu cũ.)

    Trả về chuỗi 'pbkdf2_sha256$iterations$salt_hex$hash_hex'.
    """
    if salt is None:
        salt = os.urandom(SALT_BYTES)

    derived_key = hashlib.pbkdf2_hmac(
        HASH_ALGORITHM,
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_{HASH_ALGORITHM}${PBKDF2_ITERATIONS}${salt.hex()}${derived_key.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """
    So khớp mật khẩu nhập vào với chuỗi băm đã lưu.
    Dùng hmac.compare_digest để chống tấn công đo thời gian (timing attack).
    Trả về False nếu chuỗi lưu bị sai định dạng.
    """
    try:
        scheme, iterations, salt_hex, hash_hex = stored_hash.split("$")
        if scheme != f"pbkdf2_{HASH_ALGORITHM}":
            return False

        derived_key = hashlib.pbkdf2_hmac(
            HASH_ALGORITHM,
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(derived_key.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# ----------------------------------------------------------------------
# TIỆN ÍCH
# ----------------------------------------------------------------------
def _public_user(user: Dict) -> Dict:
    """Trả về thông tin công khai của user, LOẠI BỎ password_hash."""
    return {
        "id": user["id"],
        "username": user["username"],
        "elo": user["elo"],
        "pvp_wins": user["pvp_wins"],
        "pvp_losses": user["pvp_losses"],
    }


def _fail(message: str) -> Dict:
    """Tạo phản hồi thất bại thống nhất."""
    return {"success": False, "message": message, "user": None}


# ----------------------------------------------------------------------
# ĐĂNG KÝ
# ----------------------------------------------------------------------
def register_user(username: str, password: str) -> Dict:
    """
    Đăng ký tài khoản mới.

    Kiểm tra:
        - username: 3-20 ký tự, chỉ gồm chữ cái, số và dấu gạch dưới.
        - password: từ 6 đến 128 ký tự.
        - username chưa tồn tại (không phân biệt hoa thường).

    Trả về dict: {"success": bool, "message": str, "user": dict | None}
    """
    username = (username or "").strip()
    password = password or ""

    if not USERNAME_PATTERN.match(username):
        return _fail("Tên đăng nhập phải có 3-20 ký tự gồm chữ cái, số hoặc dấu gạch dưới")

    if len(password) < MIN_PASSWORD_LENGTH:
        return _fail(f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự")
    if len(password) > MAX_PASSWORD_LENGTH:
        return _fail(f"Mật khẩu không được dài quá {MAX_PASSWORD_LENGTH} ký tự")

    if get_user_by_username(username) is not None:
        return _fail("Tên đăng nhập đã tồn tại")

    new_user_id = create_user(username, hash_password(password))
    if new_user_id is None:
        # Trường hợp hiếm: hai request đăng ký cùng tên chạy gần như đồng thời
        return _fail("Tên đăng nhập đã tồn tại")

    created_user = get_user_by_username(username)
    return {
        "success": True,
        "message": "Đăng ký thành công",
        "user": _public_user(created_user),
    }


# ----------------------------------------------------------------------
# ĐĂNG NHẬP
# ----------------------------------------------------------------------
# Chuỗi băm giả, dùng để tốn thời gian tính toán tương đương khi username
# không tồn tại, nhằm tránh lộ thông tin tài khoản nào có thật qua thời gian phản hồi.
_DUMMY_HASH = hash_password("enigma-dummy-password")


def login_user(username: str, password: str) -> Dict:
    """
    Đăng nhập.

    Trả về dict: {"success": bool, "message": str, "user": dict | None}
    Thông báo lỗi luôn chung chung ("Sai tên đăng nhập hoặc mật khẩu") để
    không tiết lộ username có tồn tại hay không.
    """
    username = (username or "").strip()
    password = password or ""

    if not username or not password:
        return _fail("Vui lòng nhập tên đăng nhập và mật khẩu")

    user = get_user_by_username(username)
    if user is None:
        verify_password(password, _DUMMY_HASH)  # cân bằng thời gian xử lý
        return _fail("Sai tên đăng nhập hoặc mật khẩu")

    if not verify_password(password, user["password_hash"]):
        return _fail("Sai tên đăng nhập hoặc mật khẩu")

    return {
        "success": True,
        "message": "Đăng nhập thành công",
        "user": _public_user(user),
    }