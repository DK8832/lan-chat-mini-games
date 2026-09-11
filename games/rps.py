from .base import BaseGame

CHOICES = {"가위": "✌", "바위": "✊", "보": "🖐"}
WINS = {"가위": "보", "바위": "가위", "보": "바위"}  # key가 value를 이김


class RockPaperScissors(BaseGame):
    NAME = "가위바위보"
    DESCRIPTION = "모두 동시에 내고 최후의 승자를 가립니다"
    GAME_KEY = "rps"
    MIN_PLAYERS = 2
    MAX_PLAYERS = 99

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.choices = {}       # {nickname: choice}
        self.scores = {}        # {nickname: wins}
        self.rounds = 1
        self.current_round = 1
        self.waiting_rounds = True

    def start(self):
        super().start()
        self.scores = {n: 0 for _, n in self.players}
        # 방장에게 판 수 선택 요청
        self.send_to(self.players[0][0], "GAME_ASK_ROUNDS")
        # 나머지는 대기
        for sock, _ in self.players[1:]:
            self.game_send(sock, "방장이 판 수를 선택하는 중입니다...")
        self.set_ready()

    def on_message(self, sock, nickname, msg):
        if not msg.startswith("GAME_INPUT:"):
            return
        val = msg[len("GAME_INPUT:"):]

        # 판 수 설정
        if self.waiting_rounds:
            if sock != self.players[0][0]:
                return
            if val.isdigit() and 1 <= int(val) <= 5:
                self.rounds = int(val)
                self.waiting_rounds = False
                self.game_broadcast(f"{self.rounds}판 진행합니다!")
                self._start_round()
            return

        # 가위/바위/보 선택
        if val not in CHOICES:
            return
        if nickname in self.choices:
            self.game_send(sock, "이미 선택했습니다")
            return
        self.choices[nickname] = val
        self.game_send(sock, f"{CHOICES[val]} 선택 완료!")
        self.game_broadcast(f"{nickname} 선택 완료 ({len(self.choices)}/{len(self.players)}명)")
        if len(self.choices) == len(self.players):
            self._resolve()

    def _start_round(self):
        self.choices = {}
        self.game_broadcast(f"[{self.current_round}/{self.rounds}라운드] 선택하세요!")
        for sock, _ in self.players:
            self.send_to(sock, "GAME_PICK")

    def _resolve(self):
        lines = [f"--- {self.current_round}라운드 결과 ---"]
        for n, c in self.choices.items():
            lines.append(f"  {n}: {CHOICES[c]} {c}")
        self.game_broadcast("\n".join(lines))

        unique = set(self.choices.values())
        if len(unique) == 1 or len(unique) == 3:
            self.game_broadcast("비겼습니다! 다시!")
            self._start_round()
            return

        winning_choice = next(c for c in unique if WINS[c] in unique)
        winners = [n for n, c in self.choices.items() if c == winning_choice]
        for w in winners:
            self.scores[w] = self.scores.get(w, 0) + 1
        self.game_broadcast(f"이번 라운드 승자: {', '.join(winners)}")

        if self.current_round >= self.rounds:
            self._finish()
        else:
            self.current_round += 1
            self._start_round()

    def _finish(self):
        max_score = max(self.scores.values())
        winners = [n for n, s in self.scores.items() if s == max_score]
        board = " | ".join(f"{n} {s}승" for n, s in
                           sorted(self.scores.items(), key=lambda x: -x[1]))
        self.game_broadcast(f"최종 결과: {board}")
        self.game_broadcast(f"최종 승자: {', '.join(winners)}!")
        self.broadcast(f"[가위바위보] 최종 승자: {', '.join(winners)}")
        self.notify_end()
        self.end_game()
