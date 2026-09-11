import random
from .base import BaseGame


class UpDown(BaseGame):
    NAME = "업다운"
    DESCRIPTION = "1~100 숫자를 번갈아 맞춥니다"
    GAME_KEY = "updown"
    MIN_PLAYERS = 1
    MAX_PLAYERS = 99

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.answer = None
        self.low = 1
        self.high = 100
        self.turn_index = 0
        self.tries = 0

    def start(self):
        super().start()
        self.answer = random.randint(1, 100)
        self.game_broadcast("업다운 시작! 1~100 숫자를 맞춰보세요!")
        self.set_ready()
        self._announce_turn()

    def _current(self):
        return self.players[self.turn_index % len(self.players)]

    def _announce_turn(self):
        cur_sock, cur_nick = self._current()
        self.game_broadcast(f"{cur_nick}의 차례!")
        self.send_to(cur_sock, f"GAME_YOUR_TURN:{self.low}:{self.high}")
        for sock, _ in self.players:
            if sock != cur_sock:
                self.send_to(sock, "GAME_WAIT")

    def on_message(self, sock, nickname, msg):
        if not msg.startswith("GAME_INPUT:"):
            return
        val = msg[len("GAME_INPUT:"):]
        cur_sock, _ = self._current()
        if sock != cur_sock:
            return
        if not val.isdigit():
            return
        guess = int(val)
        if not (1 <= guess <= 100):
            return
        self.tries += 1
        if guess == self.answer:
            self.game_broadcast(f"{nickname}이(가) {self.tries}번 만에 정답! (정답: {self.answer})")
            self.broadcast(f"[업다운] {nickname} {self.tries}번 만에 정답!")
            self.notify_end()
            self.end_game()
        elif guess < self.answer:
            self.low = max(self.low, guess + 1)
            self.game_broadcast(f"{guess} → 업! (범위: {self.low}~{self.high})")
            self.turn_index += 1
            self._announce_turn()
        else:
            self.high = min(self.high, guess - 1)
            self.game_broadcast(f"{guess} → 다운! (범위: {self.low}~{self.high})")
            self.turn_index += 1
            self._announce_turn()
