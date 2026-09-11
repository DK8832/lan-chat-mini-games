import random
from .base import BaseGame

QUESTIONS = [
    ("지구는 태양 주위를 돈다",              True),
    ("사람의 뼈는 총 200개이다",             False),  # 206개
    ("물은 100도에서 끓는다 (1기압)",         True),
    ("다이아몬드는 탄소로 이루어져 있다",      True),
    ("펭귄은 날 수 있다",                    False),
    ("소금의 화학식은 NaCl이다",              True),
    ("빛의 속도는 소리보다 느리다",           False),
    ("문어의 심장은 1개이다",                False),  # 3개
    ("벌꿀은 썩지 않는다",                   True),
    ("달은 자전하지 않는다",                 False),
    ("사람은 뇌의 10%만 사용한다",           False),
    ("금은 물에 녹지 않는다",                True),
    ("태양은 행성이다",                      False),  # 항성
    ("빨간색과 파란색을 섞으면 보라색이 된다", True),
    ("지구에서 가장 큰 나라는 러시아다",      True),
    ("번개는 같은 곳에 두 번 치지 않는다",    False),
    ("철새는 겨울에 남쪽으로 이동한다",       True),
    ("코끼리는 물을 두려워한다",             False),
    ("인간의 혈액형은 ABO식만 있다",         False),
    ("대한민국의 수도는 서울이다",            True),
]


class OXQuiz(BaseGame):
    NAME = "OX퀴즈"
    DESCRIPTION = "O 또는 X를 눌러 상식 문제를 맞춰보세요!"
    GAME_KEY = "ox"
    MIN_PLAYERS = 1
    MAX_PLAYERS = 99

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.scores = {}
        self.questions = []
        self.index = 0
        self.current_q = None
        self.answered = set()
        self.total = 7

    def start(self):
        super().start()
        self.scores = {n: 0 for _, n in self.players}
        self.questions = random.sample(QUESTIONS, min(self.total, len(QUESTIONS)))
        self.game_broadcast(f"OX퀴즈 시작! {len(self.questions)}문제!")
        self.set_ready()
        self._next()

    def _next(self):
        if self.index >= len(self.questions):
            self._finish()
            return
        self.current_q = self.questions[self.index]
        self.answered = set()
        q, _ = self.current_q
        self.game_broadcast(f"[{self.index+1}/{len(self.questions)}] {q}")
        for sock, _ in self.players:
            self.send_to(sock, f"GAME_QUESTION:{q}:{self.index+1}:{len(self.questions)}")

    def on_message(self, sock, nickname, msg):
        if not msg.startswith("GAME_INPUT:") or not self.current_q:
            return
        val = msg[len("GAME_INPUT:"):].strip().upper()
        if val not in ("O", "X"):
            return
        if nickname in self.answered:
            self.game_send(sock, "이미 답했습니다")
            return
        self.answered.add(nickname)
        _, correct = self.current_q
        correct_str = "O" if correct else "X"
        if val == correct_str:
            self.scores[nickname] = self.scores.get(nickname, 0) + 1
            self.game_send(sock, f"정답! (현재 {self.scores[nickname]}점)")
        else:
            self.game_send(sock, f"오답! 정답은 {correct_str}")
        if len(self.answered) == len(self.players):
            self.game_broadcast(f"정답: {correct_str}")
            self.index += 1
            self._next()

    def _finish(self):
        max_score = max(self.scores.values()) if self.scores else 0
        winners = [n for n, s in self.scores.items() if s == max_score]
        board = " | ".join(f"{n} {s}점" for n, s in
                           sorted(self.scores.items(), key=lambda x: -x[1]))
        self.game_broadcast(f"최종 점수: {board}")
        self.game_broadcast(f"우승: {', '.join(winners)}!")
        self.broadcast(f"[OX퀴즈] 우승: {', '.join(winners)}")
        self.notify_end()
        self.end_game()
