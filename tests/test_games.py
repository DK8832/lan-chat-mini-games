from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from games.initial import InitialQuiz
from games.liar import LiarGame
from games.ox_quiz import OXQuiz
from games.rps import RockPaperScissors
from games.updown import UpDown
from games.wordchain import WordChain


class GameHarness:
    def __init__(self, game_type, names):
        self.messages = []
        self.chat = []
        self.ended = 0
        self.sockets = [object() for _ in names]
        self.players = list(zip(self.sockets, names))
        self.game = game_type(self.chat.append, self._send, self._end)
        for sock, name in self.players:
            ok, reason = self.game.add_player(sock, name)
            if not ok:
                raise AssertionError(reason)

    def _send(self, sock, message):
        self.messages.append((sock, message))

    def _end(self):
        self.ended += 1

    def send(self, index, value):
        sock, name = self.players[index]
        self.game.on_message(sock, name, f"GAME_INPUT:{value}")


class GameRuleTest(unittest.TestCase):
    def test_rps_one_round(self):
        h = GameHarness(RockPaperScissors, ["A", "B"])
        h.game.start()
        h.send(0, "1")
        h.send(0, "가위")
        h.send(1, "보")
        self.assertEqual(1, h.ended)
        self.assertTrue(any("최종 승자: A" in message for _, message in h.messages))

    def test_updown_exact_answer(self):
        h = GameHarness(UpDown, ["A"])
        h.game.start()
        h.game.answer = 42
        h.send(0, "42")
        self.assertEqual(1, h.ended)
        self.assertTrue(any("1번 만에 정답" in message for _, message in h.messages))

    def test_wordchain_elimination(self):
        h = GameHarness(WordChain, ["A", "B"])
        h.game.start()
        h.send(0, "가나")
        h.send(1, "학교")
        self.assertEqual(1, h.ended)
        self.assertIn("[끝말잇기] 최후의 승자: A", h.chat)

    def test_initial_quiz_finish(self):
        h = GameHarness(InitialQuiz, ["A"])
        h.game.total = 1
        with patch("games.initial.random.sample", return_value=[("ㄱ", "가", "힌트")]):
            h.game.start()
        h.send(0, "가")
        self.assertEqual(1, h.ended)
        self.assertIn("[초성퀴즈] 우승: A", h.chat)

    def test_ox_quiz_all_answered(self):
        h = GameHarness(OXQuiz, ["A", "B"])
        h.game.total = 1
        with patch("games.ox_quiz.random.sample", return_value=[("참", True)]):
            h.game.start()
        h.send(0, "O")
        h.send(1, "X")
        self.assertEqual(1, h.ended)
        self.assertIn("[OX퀴즈] 우승: A", h.chat)

    def test_liar_vote_and_last_chance(self):
        h = GameHarness(LiarGame, ["A", "B", "C"])
        with patch("games.liar.random.randint", return_value=0), patch(
            "games.liar.random.choice", side_effect=lambda values: values[0]
        ):
            h.game.start()
        h.send(0, "__VOTE__")
        h.send(0, "B")
        h.send(1, "A")
        h.send(2, "A")
        self.assertEqual("last_chance", h.game.phase)
        h.send(0, h.game.word)
        self.assertEqual(1, h.ended)
        self.assertIn("[라이어게임] 라이어(A) 역전 승리", h.chat)


if __name__ == "__main__":
    unittest.main(verbosity=2)
