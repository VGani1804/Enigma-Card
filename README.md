# 🃏 ENIGMA CARD - Cyberpunk Neo-Noir Arena

**Enigma Card** là tựa game bài toán học chiến thuật lấy cảm hứng từ phong cách Cyberpunk Neo-Noir, vận hành trên kiến trúc Full-Stack Python Serverless (Vercel) kết hợp Single Page Application (Tailwind CSS / Vanilla JS).

---

## ⚡ Tính Năng Cốt Lõi

- **🧠 Mystery Value ($M$):** Giá trị bài ẩn toán học $M = (S_A + S_B) \cdot X$ được tính toán 100% bảo mật phía Python Backend.
- **🤖 AI Boss (Game Theory):** AI phân tích đảo ngược khoảng điểm bài người chơi $S_A$ thông qua $M$ để đưa ra quyết định Fold, Call, Tố (Raise) hoặc Bluff (Tố phỉnh).
- **⚔️ 3 Chế Độ Chơi:**
  - **Đấu AI:** Thách đấu Bot từ 900 đến 3,000 Elo.
  - **Đấu Xếp Hạng PvP:** Tính điểm Elo chuẩn (+25 / -20).
  - **Extreme Mode:** Áp dụng ma trận biến thiên $M = (S_A \cdot X) + (S_B \cdot Y) - Z$ với cược Pot x2.
- **⏱️ Chess Clock:** Đếm ngược 30 giây mỗi lượt đấu.

---

## 📁 Cấu Trúc Thư Mục

```text
enigma-card/
├── api/
│   └── index.py             # Serverless Entry Point (Flask API)
├── modules/
│   ├── game_engine.py       # Core Algorithms (AI, M calculation, Elo)
│   ├── auth.py              # Xử lý Đăng ký, Đăng nhập
│   └── database.py          # SQLite Database Manager
├── public/
│   ├── index.html           # UI Single Page Application
│   └── app.js               # Client Logic & Kết nối API
├── vercel.json              # Routing Serverless Configuration
└── requirements.txt         # Dependencies (Flask, gunicorn)