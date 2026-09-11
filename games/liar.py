import random
from .base import BaseGame

TOPICS = [
    ("음식",   ["피자", "햄버거", "라면", "삼겹살", "치킨", "초밥", "파스타", "떡볶이", "순대", "족발"]),
    ("동물",   ["강아지", "고양이", "토끼", "햄스터", "앵무새", "거북이", "금붕어", "코끼리", "기린", "펭귄"]),
    ("스포츠", ["축구", "야구", "농구", "배구", "테니스", "수영", "달리기", "태권도", "골프", "배드민턴"]),
    ("나라",   ["한국", "미국", "일본", "중국", "프랑스", "영국", "독일", "이탈리아", "스페인", "브라질"]),
    ("직업",   ["의사", "선생님", "경찰", "소방관", "요리사", "가수", "배우", "작가", "화가", "운동선수"]),
]


class LiarGame(BaseGame):
    NAME = "라이어게임"
    DESCRIPTION = "라이어는 주제어를 모릅니다. 투표로 찾아내세요!"
    GAME_KEY = "liar"
    MIN_PLAYERS = 3
    MAX_PLAYERS = 10

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.liar_sock = None
        self.liar_nick = None
        self.topic = None
        self.word = None
        self.phase = "describe"  # describe → vote → last_chance
        self.votes = {}

    def start(self):
        super().start()
        idx = random.randint(0, len(self.players) - 1)
        self.liar_sock, self.liar_nick = self.players[idx]
        self.topic, words = random.choice(TOPICS)
        self.word = random.choice(words)

        for sock, nick in self.players:
            if sock == self.liar_sock:
                self.send_to(sock, f"GAME_ROLE:liar:{self.topic}:")
            else:
                self.send_to(sock, f"GAME_ROLE:citizen:{self.topic}:{self.word}")

        self.game_broadcast(f"라이어게임 시작! 주제: {self.topic}")
        self.game_broadcast("각자 단어를 설명하세요. 방장이 투표 버튼을 누르면 투표 시작")
        # 방장에게 투표 시작 버튼 활성화 신호
        self.send_to(self.players[0][0], "GAME_HOST")
        self.set_ready()

    def on_message(self, sock, nickname, msg):
        if self.phase == "describe":
            if msg == "GAME_INPUT:__VOTE__":
                if sock != self.players[0][0]:
                    self.game_send(sock, "방장만 투표를 시작할 수 있습니다")
                    return
                self._start_vote()
            elif msg.startswith("GAME_INPUT:"):
                # 설명 채팅
                text = msg[len("GAME_INPUT:"):]
                self.game_broadcast(f"{nickname}: {text}")

        elif self.phase == "vote":
            if not msg.startswith("GAME_INPUT:"):
                return
            target = msg[len("GAME_INPUT:"):]
            if nickname in self.votes:
                self.game_send(sock, "이미 투표했습니다")
                return
            nicks = [n for _, n in self.players]
            if target not in nicks:
                self.game_send(sock, "없는 닉네임입니다")
                return
            if target == nickname:
                self.game_send(sock, "자신에게는 투표할 수 없습니다")
                return
            self.votes[nickname] = target
            self.game_broadcast(f"{nickname} 투표 완료 ({len(self.votes)}/{len(self.players)})")
            if len(self.votes) == len(self.players):
                self._resolve()

        elif self.phase == "last_chance":
            if sock != self.liar_sock or not msg.startswith("GAME_INPUT:"):
                return
            val = msg[len("GAME_INPUT:"):]
            if val == self.word:
                self.game_broadcast(f"라이어 {self.liar_nick}이 단어를 맞췄습니다! 역전 승리!")
                self.broadcast(f"[라이어게임] 라이어({self.liar_nick}) 역전 승리")
            else:
                self.game_broadcast(f"틀렸습니다! 시민 최종 승리! (정답: {self.word})")
                self.broadcast(f"[라이어게임] 시민 승리")
            self.notify_end()
            self.end_game()

    def _start_vote(self):
        self.phase = "vote"
        nicks = [n for _, n in self.players]
        self.game_broadcast("투표 시작! 라이어라고 생각하는 사람을 선택하세요")
        for sock, _ in self.players:
            self.send_to(sock, f"GAME_VOTE:{','.join(nicks)}")

    def _resolve(self):
        tally = {}
        for t in self.votes.values():
            tally[t] = tally.get(t, 0) + 1
        most = max(tally.values())
        suspects = [n for n, v in tally.items() if v == most]
        result = " | ".join(f"{n} {v}표" for n, v in
                            sorted(tally.items(), key=lambda x: -x[1]))
        self.game_broadcast(f"투표 결과: {result}")

        if self.liar_nick in suspects and len(suspects) == 1:
            self.game_broadcast(f"라이어 {self.liar_nick} 적발! 시민 승리!")
            self.send_to(self.liar_sock, "GAME_LAST_CHANCE")
            self.game_broadcast("라이어의 마지막 기회! 단어를 맞추면 역전!")
            self.phase = "last_chance"
        else:
            self.game_broadcast(f"라이어 {self.liar_nick} 생존! 라이어 승리!")
            self.game_broadcast(f"정답 단어는 「{self.word}」였습니다")
            self.broadcast(f"[라이어게임] 라이어({self.liar_nick}) 승리")
            self.notify_end()
            self.end_game()