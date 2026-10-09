/**
 * public/app.js
 * =============
 * Frontend Vanilla JS cho Enigma Card.
 *
 * Luồng một ván đấu:
 *   startNewMatch()  -> POST /api/game/start
 *   playerAction()   -> POST /api/game/bot-turn   (người chơi CALL hoặc FOLD)
 *   processShowdown()-> POST /api/game/showdown   (tự động gọi sau bot-turn)
 *
 * CÁC ID / THUỘC TÍNH HTML MÀ FILE NÀY SỬ DỤNG (phần tử nào thiếu sẽ bị bỏ qua,
 * không gây lỗi):
 *
 *   Tab:
 *     [data-tab-btn="game"]     nút chuyển tab (giá trị = tên tab)
 *     [data-tab-panel="game"]   vùng nội dung của tab đó
 *
 *   Điều khiển:
 *     #btn-start                nút "Bắt đầu ván mới"
 *     #btn-call                 nút "Theo" (CALL)
 *     #btn-fold                 nút "Bỏ bài" (FOLD)
 *     #mode-select              <select> với option AI / PVP / EXTREME
 *     #bot-elo-input            <input type="number"> Elo của Bot
 *
 *   Hiển thị:
 *     #player-hand              khu vực bài tẩy người chơi
 *     #board-cards              khu vực 5 lá bài bàn
 *     #mystery-value            giá trị Mystery Value
 *     #pot-value                tổng Pot
 *     #timer-display            đồng hồ đếm ngược
 *     #game-status              dòng thông báo trạng thái
 *     #bot-action-display       hành động của Bot
 *     #mode-display             tên chế độ đang chơi
 *     #player-elo-display       Elo của người chơi
 *     #result-panel             khung kết quả (ẩn/hiện bằng class "hidden")
 *     #result-title             WIN / LOSE / DRAW
 *     #result-details           chi tiết điểm, Pot, Elo
 *     #bot-hand                 bài tẩy Bot (chỉ hiện ở showdown)
 *
 * LƯU Ý: Các nút đã được gắn sự kiện bằng addEventListener trong init().
 * KHÔNG gắn thêm thuộc tính onclick="..." cho cùng các nút đó để tránh gọi 2 lần.
 */

"use strict";

// ======================================================================
// HẰNG SỐ
// ======================================================================
const API_ENDPOINTS = {
    START: "/api/game/start",
    BOT_TURN: "/api/game/bot-turn",
    SHOWDOWN: "/api/game/showdown",
};

const TURN_SECONDS = 30;                       // Thời gian mỗi lượt (giây)
const TIMER_WARNING_SECONDS = 10;              // Dưới mốc này đồng hồ chuyển đỏ
const DEFAULT_PLAYER_ELO = 1000;               // Elo khởi điểm người chơi
const ELO_STORAGE_KEY = "enigma_player_elo";   // Khóa lưu Elo trong localStorage
const SHOWDOWN_DELAY_MS = 900;                 // Chờ để người chơi thấy hành động của Bot

// ======================================================================
// TRẠNG THÁI TOÀN CỤC CỦA VÁN ĐẤU
// ======================================================================
const gameState = {
    activeTab: "game",       // Tab đang mở
    phase: "idle",           // 'idle' | 'playing' | 'resolving' | 'finished'
    busy: false,             // true khi đang chờ phản hồi từ server

    gameId: null,            // ID ván đấu do server cấp
    mode: "AI",              // 'AI' | 'PVP' | 'EXTREME'
    botElo: 1000,            // Elo của Bot

    playerHand: [],          // 2 lá bài tẩy của người chơi
    boardCards: [],          // 5 lá bài bàn (X, Y, Z, ...)
    mysteryValue: null,      // Mystery Value M
    pot: 0,                  // Tổng Pot hiện tại

    playerAction: null,      // 'CALL' | 'FOLD'
    botAction: null,         // 'CALL' | 'FOLD' | 'RAISE'
    botRaiseAmount: 0,       // Số điểm Bot tố thêm

    result: null,            // Toàn bộ phản hồi của /showdown
    playerElo: DEFAULT_PLAYER_ELO,

    timeLeft: TURN_SECONDS,  // Số giây còn lại của lượt
    timerId: null,           // ID của setInterval
};

// ======================================================================
// HÀM TIỆN ÍCH DOM
// ======================================================================

/** Lấy phần tử theo id (trả về null nếu không có). */
function $(id) {
    return document.getElementById(id);
}

/** Gán textContent cho phần tử theo id nếu phần tử tồn tại. */
function setText(id, text) {
    const element = $(id);
    if (element) {
        element.textContent = text;
    }
}

/** Ẩn hoặc hiện phần tử bằng class "hidden" của Tailwind. */
function setHidden(id, hidden) {
    const element = $(id);
    if (element) {
        element.classList.toggle("hidden", hidden);
    }
}

/** Bật/tắt thuộc tính disabled cho nút theo id. */
function setDisabled(id, disabled) {
    const element = $(id);
    if (element) {
        element.disabled = disabled;
        element.classList.toggle("opacity-50", disabled);
        element.classList.toggle("cursor-not-allowed", disabled);
    }
}

/** Hiển thị dòng trạng thái. type: 'info' | 'success' | 'error' | 'warning'. */
function setStatus(message, type = "info") {
    const element = $("game-status");
    if (!element) {
        return;
    }
    const colorClasses = {
        info: "text-cyan-300",
        success: "text-green-400",
        error: "text-red-400",
        warning: "text-yellow-300",
    };
    Object.values(colorClasses).forEach((cls) => element.classList.remove(cls));
    element.classList.add(colorClasses[type] || colorClasses.info);
    element.textContent = message;
}

/** Hàm chờ dạng Promise. */
function sleep(milliseconds) {
    return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

/**
 * Tạo một phần tử lá bài.
 * @param {number|string} value  Giá trị hiển thị trên lá bài.
 * @param {string} label         Nhãn nhỏ phía trên (ví dụ 'X', 'Y', 'Z'); có thể để trống.
 * @param {boolean} hidden       true -> hiển thị mặt úp '?'.
 */
function createCardElement(value, label = "", hidden = false) {
    const wrapper = document.createElement("div");
    wrapper.className = "flex flex-col items-center gap-1";

    if (label) {
        const labelElement = document.createElement("span");
        labelElement.className = "text-xs font-mono text-fuchsia-400";
        labelElement.textContent = label;
        wrapper.appendChild(labelElement);
    }

    const card = document.createElement("div");
    card.className = hidden
        ? "w-14 h-20 flex items-center justify-center rounded-lg border-2 border-gray-600 " +
          "bg-gray-800 text-gray-500 text-2xl font-bold font-mono"
        : "w-14 h-20 flex items-center justify-center rounded-lg border-2 border-cyan-400 " +
          "bg-gray-900 text-cyan-300 text-2xl font-bold font-mono shadow-lg shadow-cyan-500/30";
    card.textContent = hidden ? "?" : String(value);
    wrapper.appendChild(card);

    return wrapper;
}

// ======================================================================
// LƯU TRỮ ELO NGƯỜI CHƠI
// ======================================================================

/** Đọc Elo người chơi từ localStorage (có xử lý khi bị chặn hoặc dữ liệu hỏng). */
function loadPlayerElo() {
    try {
        const stored = parseInt(localStorage.getItem(ELO_STORAGE_KEY), 10);
        gameState.playerElo = Number.isFinite(stored) && stored >= 0 ? stored : DEFAULT_PLAYER_ELO;
    } catch (error) {
        gameState.playerElo = DEFAULT_PLAYER_ELO;
    }
}

/** Ghi Elo người chơi vào localStorage. */
function savePlayerElo() {
    try {
        localStorage.setItem(ELO_STORAGE_KEY, String(gameState.playerElo));
    } catch (error) {
        // Bỏ qua nếu trình duyệt chặn localStorage
    }
}

// ======================================================================
// GỌI API
// ======================================================================

/**
 * Gửi POST JSON và trả về dữ liệu JSON.
 * Ném Error (kèm thông báo tiếng Việt) khi mạng lỗi, phản hồi không phải JSON,
 * hoặc server trả success=false.
 */
async function apiPost(url, body) {
    let response;
    try {
        response = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body || {}),
        });
    } catch (networkError) {
        throw new Error("Không thể kết nối tới máy chủ. Vui lòng kiểm tra mạng.");
    }

    let data;
    try {
        data = await response.json();
    } catch (parseError) {
        throw new Error(`Máy chủ trả về dữ liệu không hợp lệ (HTTP ${response.status}).`);
    }

    if (!response.ok || !data.success) {
        const error = new Error(data.error || `Yêu cầu thất bại (HTTP ${response.status}).`);
        error.status = response.status;
        throw error;
    }
    return data;
}

// ======================================================================
// CHUYỂN TAB
// ======================================================================

/**
 * Hiển thị tab có tên tabName và ẩn các tab còn lại.
 * Trả về true nếu tìm thấy tab, false nếu không.
 */
function switchTab(tabName) {
    const panels = document.querySelectorAll("[data-tab-panel]");
    let found = false;

    panels.forEach((panel) => {
        const isTarget = panel.dataset.tabPanel === tabName;
        panel.classList.toggle("hidden", !isTarget);
        if (isTarget) {
            found = true;
        }
    });

    if (!found) {
        console.warn(`switchTab: không tìm thấy tab "${tabName}"`);
        return false;
    }

    const buttons = document.querySelectorAll("[data-tab-btn]");
    buttons.forEach((button) => {
        const isActive = button.dataset.tabBtn === tabName;
        button.classList.toggle("border-cyan-400", isActive);
        button.classList.toggle("text-cyan-300", isActive);
        button.classList.toggle("border-transparent", !isActive);
        button.classList.toggle("text-gray-400", !isActive);
    });

    gameState.activeTab = tabName;
    return true;
}

// ======================================================================
// ĐẾM NGƯỢC 30 GIÂY
// ======================================================================

/** Cập nhật hiển thị đồng hồ và đổi màu khi sắp hết giờ. */
function renderTimer() {
    const element = $("timer-display");
    if (!element) {
        return;
    }
    element.textContent = `${gameState.timeLeft}s`;
    const isWarning = gameState.timeLeft <= TIMER_WARNING_SECONDS;
    element.classList.toggle("text-red-500", isWarning);
    element.classList.toggle("animate-pulse", isWarning);
    element.classList.toggle("text-cyan-300", !isWarning);
}

/** Dừng đồng hồ đếm ngược (an toàn khi gọi nhiều lần). */
function stopCountdown() {
    if (gameState.timerId !== null) {
        clearInterval(gameState.timerId);
        gameState.timerId = null;
    }
}

/**
 * Bắt đầu đếm ngược từ `seconds` giây (mặc định 30).
 * Khi về 0 mà người chơi chưa hành động, tự động FOLD.
 */
function startCountdown(seconds = TURN_SECONDS) {
    stopCountdown();
    gameState.timeLeft = seconds;
    renderTimer();

    gameState.timerId = setInterval(() => {
        gameState.timeLeft -= 1;
        renderTimer();

        if (gameState.timeLeft <= 0) {
            stopCountdown();
            if (gameState.phase === "playing" && !gameState.busy) {
                setStatus("Hết giờ! Hệ thống tự động bỏ bài.", "warning");
                playerAction("FOLD");
            }
        }
    }, 1000);
}

// ======================================================================
// VẼ BÀN CHƠI
// ======================================================================

/** Vẽ toàn bộ bàn chơi dựa trên gameState hiện tại. */
function renderGameBoard() {
    // Bài tẩy người chơi
    const handContainer = $("player-hand");
    if (handContainer) {
        handContainer.replaceChildren();
        gameState.playerHand.forEach((value, index) => {
            handContainer.appendChild(createCardElement(value, `Lá ${index + 1}`));
        });
    }

    // Bài bàn: ba lá đầu mang nhãn X, Y, Z
    const boardContainer = $("board-cards");
    if (boardContainer) {
        boardContainer.replaceChildren();
        const boardLabels = ["X", "Y", "Z"];
        gameState.boardCards.forEach((value, index) => {
            const label = index < boardLabels.length ? boardLabels[index] : `#${index + 1}`;
            boardContainer.appendChild(createCardElement(value, label));
        });
    }

    // Các thông số
    setText("mystery-value", gameState.mysteryValue === null ? "--" : String(gameState.mysteryValue));
    setText("pot-value", String(gameState.pot));
    setText("mode-display", gameState.mode);
    setText("player-elo-display", String(gameState.playerElo));

    // Hành động của Bot
    let botText = "Đang chờ...";
    if (gameState.botAction === "RAISE") {
        botText = `TỐ (+${gameState.botRaiseAmount})`;
    } else if (gameState.botAction === "CALL") {
        botText = "THEO";
    } else if (gameState.botAction === "FOLD") {
        botText = "BỎ BÀI";
    }
    setText("bot-action-display", botText);

    // Bài tẩy Bot: úp cho tới khi showdown
    const botHandContainer = $("bot-hand");
    if (botHandContainer) {
        botHandContainer.replaceChildren();
        if (gameState.phase === "finished" && gameState.result) {
            gameState.result.bot_hand.forEach((value) => {
                botHandContainer.appendChild(createCardElement(value));
            });
        } else if (gameState.phase !== "idle") {
            botHandContainer.appendChild(createCardElement("?", "", true));
            botHandContainer.appendChild(createCardElement("?", "", true));
        }
    }

    // Trạng thái các nút
    const canAct = gameState.phase === "playing" && !gameState.busy;
    setDisabled("btn-call", !canAct);
    setDisabled("btn-fold", !canAct);
    setDisabled("btn-start", gameState.busy || gameState.phase === "playing" || gameState.phase === "resolving");

    renderTimer();
}

/** Hiển thị khung kết quả sau showdown. */
function renderShowdownResult() {
    const result = gameState.result;
    if (!result) {
        return;
    }

    const titles = {
        WIN: "CHIẾN THẮNG",
        LOSE: "THẤT BẠI",
        DRAW: "HÒA",
    };
    const titleElement = $("result-title");
    if (titleElement) {
        titleElement.textContent = titles[result.result] || result.result;
        titleElement.classList.remove("text-green-400", "text-red-400", "text-yellow-300");
        titleElement.classList.add(
            result.result === "WIN" ? "text-green-400"
                : result.result === "LOSE" ? "text-red-400"
                    : "text-yellow-300"
        );
    }

    const eloSign = result.elo_change > 0 ? "+" : "";
    const bluffNote = result.bot_bluffed ? " (Bot đã bluff!)" : "";
    setText(
        "result-details",
        `Điểm của bạn: ${result.player_score} | Điểm của Bot: ${result.bot_score}${bluffNote}\n` +
        `Pot nhận được: ${result.pot_won} / ${result.pot}\n` +
        `Elo: ${eloSign}${result.elo_change} (mới: ${result.new_player_elo})`
    );
    const detailsElement = $("result-details");
    if (detailsElement) {
        detailsElement.style.whiteSpace = "pre-line";
    }

    setHidden("result-panel", false);
}

// ======================================================================
// BẮT ĐẦU VÁN MỚI
// ======================================================================

/**
 * Gọi POST /api/game/start để tạo ván đấu mới.
 * @param {string} [mode]    'AI' | 'PVP' | 'EXTREME'. Nếu bỏ trống sẽ đọc từ #mode-select.
 * @param {number} [botElo]  Elo của Bot. Nếu bỏ trống sẽ đọc từ #bot-elo-input.
 */
async function startNewMatch(mode, botElo) {
    if (gameState.busy || gameState.phase === "playing" || gameState.phase === "resolving") {
        return;
    }

    const selectedMode = mode || ($("mode-select") ? $("mode-select").value : "AI") || "AI";
    const parsedBotElo = parseInt(
        botElo !== undefined ? botElo : ($("bot-elo-input") ? $("bot-elo-input").value : 1000),
        10
    );
    const selectedBotElo = Number.isFinite(parsedBotElo) ? parsedBotElo : 1000;

    stopCountdown();
    gameState.busy = true;
    setHidden("result-panel", true);
    setStatus("Đang khởi tạo ván đấu...", "info");
    renderGameBoard();

    try {
        const data = await apiPost(API_ENDPOINTS.START, {
            mode: selectedMode,
            bot_elo: selectedBotElo,
        });

        // Ghi nhận dữ liệu ván mới (server KHÔNG trả bài của Bot)
        gameState.gameId = data.game_id;
        gameState.mode = data.mode;
        gameState.botElo = selectedBotElo;
        gameState.playerHand = data.player_hand;
        gameState.boardCards = data.board_cards;
        gameState.mysteryValue = data.mystery_value;
        gameState.pot = data.pot;
        gameState.playerAction = null;
        gameState.botAction = null;
        gameState.botRaiseAmount = 0;
        gameState.result = null;
        gameState.phase = "playing";
        gameState.busy = false;

        switchTab("game");
        renderGameBoard();
        setStatus("Ván đấu bắt đầu! Hãy chọn THEO hoặc BỎ BÀI.", "success");
        startCountdown(TURN_SECONDS);
    } catch (error) {
        gameState.busy = false;
        gameState.phase = "idle";
        renderGameBoard();
        setStatus(error.message, "error");
    }
}

// ======================================================================
// HÀNH ĐỘNG CỦA NGƯỜI CHƠI
// ======================================================================

/**
 * Người chơi chọn hành động, sau đó gọi POST /api/game/bot-turn để Bot phản hồi.
 * Khi Bot đã hành động xong, tự động gọi processShowdown().
 * @param {string} action  'CALL' hoặc 'FOLD'.
 */
async function playerAction(action) {
    if (gameState.phase !== "playing" || gameState.busy) {
        return;
    }

    const normalizedAction = String(action || "").toUpperCase();
    if (normalizedAction !== "CALL" && normalizedAction !== "FOLD") {
        setStatus("Hành động không hợp lệ (chỉ nhận CALL hoặc FOLD).", "error");
        return;
    }

    stopCountdown();
    gameState.busy = true;
    gameState.playerAction = normalizedAction;
    renderGameBoard();
    setStatus(
        normalizedAction === "FOLD" ? "Bạn bỏ bài. Đang chờ Bot..." : "Bạn theo. Bot đang suy nghĩ...",
        "info"
    );

    try {
        const data = await apiPost(API_ENDPOINTS.BOT_TURN, { game_id: gameState.gameId });

        gameState.botAction = data.action;
        gameState.botRaiseAmount = data.raise_amount;
        gameState.pot = data.pot;
        gameState.phase = "resolving";
        gameState.busy = false;
        renderGameBoard();

        if (data.action === "RAISE") {
            setStatus(`Bot TỐ thêm ${data.raise_amount}! Pot hiện tại: ${data.pot}.`, "warning");
        } else if (data.action === "CALL") {
            setStatus("Bot THEO.", "info");
        } else {
            setStatus("Bot BỎ BÀI!", "success");
        }

        // Chờ một chút để người chơi kịp thấy hành động của Bot rồi mở bài
        await sleep(SHOWDOWN_DELAY_MS);
        await processShowdown();
    } catch (error) {
        gameState.busy = false;

        // Ván đấu không còn trên server (hết hạn hoặc instance khác): quay về trạng thái chờ
        if (error.status === 404) {
            gameState.phase = "idle";
            renderGameBoard();
            setStatus(`${error.message} Hãy bắt đầu ván mới.`, "error");
            return;
        }

        // Lỗi khác: cho phép thử lại và tiếp tục đếm ngược từ thời gian còn lại
        gameState.phase = "playing";
        gameState.playerAction = null;
        renderGameBoard();
        setStatus(error.message, "error");
        startCountdown(Math.max(gameState.timeLeft, 5));
    }
}

// ======================================================================
// SHOWDOWN
// ======================================================================

/**
 * Gọi POST /api/game/showdown, cập nhật Elo và hiển thị kết quả.
 * Thường được gọi tự động từ playerAction().
 */
async function processShowdown() {
    if (!gameState.gameId || gameState.busy) {
        return;
    }
    if (gameState.phase !== "resolving") {
        return;
    }

    gameState.busy = true;
    setStatus("Đang mở bài...", "info");
    renderGameBoard();

    try {
        const data = await apiPost(API_ENDPOINTS.SHOWDOWN, {
            game_id: gameState.gameId,
            player_action: gameState.playerAction || "CALL",
            player_elo: gameState.playerElo,
        });

        gameState.result = data;
        gameState.pot = data.pot;
        gameState.playerElo = data.new_player_elo;
        savePlayerElo();

        gameState.phase = "finished";
        gameState.busy = false;

        renderGameBoard();
        renderShowdownResult();

        if (data.result === "WIN") {
            setStatus("Bạn thắng ván này!", "success");
        } else if (data.result === "LOSE") {
            setStatus("Bạn thua ván này.", "error");
        } else {
            setStatus("Ván đấu hòa.", "warning");
        }
    } catch (error) {
        gameState.busy = false;
        gameState.phase = error.status === 404 ? "idle" : "resolving";
        renderGameBoard();
        setStatus(error.message, "error");

        // Lỗi tạm thời (mạng): thử mở bài lại sau 2 giây
        if (error.status !== 404 && error.status !== 409) {
            setTimeout(() => {
                if (gameState.phase === "resolving" && !gameState.busy) {
                    processShowdown();
                }
            }, 2000);
        }
    }
}

// ======================================================================
// KHỞI TẠO
// ======================================================================

/** Gắn sự kiện cho các nút và vẽ giao diện ban đầu. */
function init() {
    loadPlayerElo();

    // Nút điều khiển ván đấu
    const startButton = $("btn-start");
    if (startButton) {
        startButton.addEventListener("click", () => startNewMatch());
    }
    const callButton = $("btn-call");
    if (callButton) {
        callButton.addEventListener("click", () => playerAction("CALL"));
    }
    const foldButton = $("btn-fold");
    if (foldButton) {
        foldButton.addEventListener("click", () => playerAction("FOLD"));
    }

    // Nút chuyển tab
    document.querySelectorAll("[data-tab-btn]").forEach((button) => {
        button.addEventListener("click", () => switchTab(button.dataset.tabBtn));
    });

    // Mở tab mặc định nếu có
    if (document.querySelector("[data-tab-panel]")) {
        switchTab(gameState.activeTab);
    }

    setHidden("result-panel", true);
    renderGameBoard();
    setStatus("Nhấn BẮT ĐẦU để vào ván đấu.", "info");
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
} else {
    init();
}