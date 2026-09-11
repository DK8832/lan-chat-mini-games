class BaseGame:
    NAME = "게임"
    DESCRIPTION = ""
    GAME_KEY = ""       # 클라이언트 팝업 식별자
    MIN_PLAYERS = 2
    MAX_PLAYERS = 99

    def __init__(self, broadcast_fn, send_to_fn, end_game_fn):
        self.broadcast = broadcast_fn   # 채팅방 전체 전송
        self.send_to = send_to_fn       # 특정 소켓에 전송
        self.end_game = end_game_fn     # 방 종료 콜백
        self.players = []               # [(sock, nickname), ...]
        self.started = False
        self.ready = False

    # ── 플레이어 관리 ──────────────────────────
    def add_player(self, sock, nickname):
        if self.started:
            return False, "이미 게임이 시작됐습니다"
        if len(self.players) >= self.MAX_PLAYERS:
            return False, f"최대 {self.MAX_PLAYERS}명까지 참가 가능합니다"
        if any(s == sock for s, _ in self.players):
            return False, "이미 참가했습니다"
        self.players.append((sock, nickname))
        return True, ""

    def remove_player(self, sock):
        self.players = [(s, n) for s, n in self.players if s != sock]
        if self.started and len(self.players) < self.MIN_PLAYERS:
            self.game_broadcast("인원 부족으로 게임이 종료됩니다")
            self.end_game()

    # ── 전송 헬퍼 ─────────────────────────────
    def game_broadcast(self, msg):
        """게임 참가자 전원의 팝업창에 메시지 전송"""
        for sock, _ in self.players:
            self.send_to(sock, f"GAME_MSG:{msg}")

    def game_send(self, sock, msg):
        """특정 참가자의 팝업창에 메시지 전송"""
        self.send_to(sock, f"GAME_MSG:{msg}")

    # ── 신호 ──────────────────────────────────
    def notify_start(self):
        """게임 시작 → 클라이언트 팝업 오픈"""
        for sock, _ in self.players:
            self.send_to(sock, f"GAME_START:{self.GAME_KEY}")

    def notify_end(self):
        """게임 종료 → 클라이언트 팝업 닫기"""
        for sock, _ in self.players:
            self.send_to(sock, "GAME_END")

    def set_ready(self):
        """입력 받을 준비 완료"""
        self.ready = True

    # ── 오버라이드 ────────────────────────────
    def start(self):
        self.started = True
        self.ready = False
        self.notify_start()

    def on_message(self, sock, nickname, msg):
        """게임 입력 처리. 서브클래스에서 구현."""
        pass
