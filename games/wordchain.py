from .base import BaseGame


class WordChain(BaseGame):
    NAME = "끝말잇기"
    DESCRIPTION = "앞 단어의 마지막 글자로 시작하는 단어를 이어가세요"
    GAME_KEY = "wordchain"
    MIN_PLAYERS = 2
    MAX_PLAYERS = 99

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.used = set()
        self.last_word = None
        self.turn_index = 0

    def start(self):
        super().start()
        self.game_broadcast("끝말잇기 시작!")
        self.set_ready()
        self._announce_turn()

    def _current(self):
        return self.players[self.turn_index % len(self.players)]

    def _announce_turn(self):
        cur_sock, cur_nick = self._current()
        hint = self.last_word[-1] if self.last_word else ""
        self.game_broadcast(
            f"{cur_nick}의 차례!" +
            (f" 「{hint}」으로 시작하는 단어:" if hint else " 첫 단어를 입력하세요")
        )
        self.send_to(cur_sock, f"GAME_YOUR_TURN:{hint}")
        for sock, _ in self.players:
            if sock != cur_sock:
                self.send_to(sock, "GAME_WAIT")

    def on_message(self, sock, nickname, msg):
        if not msg.startswith("GAME_INPUT:"):
            return
        word = msg[len("GAME_INPUT:"):].strip()
        cur_sock, _ = self._current()
        if sock != cur_sock:
            return
        if len(word) < 2:
            self.game_send(sock, "2글자 이상 입력하세요")
            self.send_to(sock, f"GAME_YOUR_TURN:{self.last_word[-1] if self.last_word else ''}")
            return
        if not all('\uAC00' <= c <= '\uD7A3' for c in word):
            self.game_send(sock, "한국어 단어만 입력 가능합니다")
            self.send_to(sock, f"GAME_YOUR_TURN:{self.last_word[-1] if self.last_word else ''}")
            return
        if self.last_word and word[0] != self.last_word[-1]:
            self._eliminate(sock, nickname, f"「{self.last_word[-1]}」으로 시작해야 합니다")
            return
        if word in self.used:
            self._eliminate(sock, nickname, f"「{word}」은 이미 사용된 단어입니다")
            return

        self.used.add(word)
        self.last_word = word
        self.game_broadcast(f"{nickname}: {word}")
        self.turn_index += 1
        self._announce_turn()

    def _eliminate(self, sock, nickname, reason):
        self.game_broadcast(f"{nickname} 탈락! {reason}")
        self.send_to(sock, "GAME_ELIMINATED")
        self.players = [(s, n) for s, n in self.players if s != sock]

        if len(self.players) == 1:
            winner = self.players[0][1]
            self.game_broadcast(f"최후의 승자: {winner}!")
            self.broadcast(f"[끝말잇기] 최후의 승자: {winner}")
            self.notify_end()
            self.end_game()
        elif not self.players:
            self.game_broadcast("모두 탈락했습니다!")
            self.notify_end()
            self.end_game()
        else:
            self.turn_index = self.turn_index % len(self.players)
            self._announce_turn()
