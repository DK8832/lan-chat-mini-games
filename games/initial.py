import random
from .base import BaseGame

QUESTIONS = [
    ("ㄱㅇㅂㅇㅂ", "가위바위보", "손으로 하는 게임"),
    ("ㄴㄹ",       "노래",     "입으로 하는 것"),
    ("ㅎㄱ",       "학교",     "학생이 가는 곳"),
    ("ㅊㅋ",       "축하",     "좋은 일이 생겼을 때"),
    ("ㅅㄹ",       "사랑",     "따뜻한 감정"),
    ("ㅂㄹ",       "바람",     "공기의 흐름"),
    ("ㄱㅅ",       "감사",     "고마움을 표현할 때"),
    ("ㅎㅂ",       "행복",     "기쁨과 만족의 상태"),
    ("ㅊㄱ",       "축구",     "발로 하는 스포츠"),
    ("ㄴㅅ",       "낚시",     "물고기를 잡는 취미"),
    ("ㅁㅅ",       "미소",     "입꼬리가 올라가는 표정"),
    ("ㄱㅇ",       "기억",     "과거를 떠올리는 것"),
    ("ㄷㄱ",       "달걀",     "닭이 낳는 것"),
    ("ㅅㅂ",       "수박",     "여름 과일"),
    ("ㅂㄷㅁㅌ",   "배드민턴", "셔틀콕을 치는 스포츠"),
    ("ㅌㄱㄱ",     "태극기",   "우리나라 국기"),
    ("ㅍㅇㄴ",     "피아노",   "건반 악기"),
    ("ㅎㄹ",       "하루",     "24시간"),
    ("ㅇㅅ",       "영수증",   "구매 후 받는 종이"),
    ("ㄱㅈ",       "기차",     "철로 위를 달리는 교통수단"),
]


class InitialQuiz(BaseGame):
    NAME = "초성퀴즈"
    DESCRIPTION = "초성을 보고 단어를 맞춰보세요!"
    GAME_KEY = "initial"
    MIN_PLAYERS = 1
    MAX_PLAYERS = 99

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.scores = {}
        self.questions = []
        self.index = 0
        self.current_q = None
        self.total = 7

    def start(self):
        super().start()
        self.scores = {n: 0 for _, n in self.players}
        self.questions = random.sample(QUESTIONS, min(self.total, len(QUESTIONS)))
        self.game_broadcast(f"초성퀴즈 시작! {len(self.questions)}문제!")
        self.set_ready()
        self._next()

    def _next(self):
        if self.index >= len(self.questions):
            self._finish()
            return
        self.current_q = self.questions[self.index]
        initial, _, hint = self.current_q
        self.game_broadcast(f"[{self.index+1}/{len(self.questions)}] 초성: {initial}  힌트: {hint}")
        for sock, _ in self.players:
            self.send_to(sock, f"GAME_QUESTION:{initial}:{hint}:{self.index+1}:{len(self.questions)}")

    def on_message(self, sock, nickname, msg):
        if not msg.startswith("GAME_INPUT:") or not self.current_q:
            return
        val = msg[len("GAME_INPUT:"):].strip()
        _, answer, _ = self.current_q
        if val == answer:
            self.scores[nickname] = self.scores.get(nickname, 0) + 1
            self.game_broadcast(f"{nickname} 정답! 「{answer}」 ({self.scores[nickname]}점)")
            self.index += 1
            self.current_q = None
            self._next()

    def _finish(self):
        max_score = max(self.scores.values()) if self.scores else 0
        winners = [n for n, s in self.scores.items() if s == max_score]
        board = " | ".join(f"{n} {s}점" for n, s in
                           sorted(self.scores.items(), key=lambda x: -x[1]))
        self.game_broadcast(f"최종 점수: {board}")
        self.game_broadcast(f"우승: {', '.join(winners)}!")
        self.broadcast(f"[초성퀴즈] 우승: {', '.join(winners)}")
        self.notify_end()
        self.end_game()
