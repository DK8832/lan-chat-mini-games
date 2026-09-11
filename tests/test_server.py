from __future__ import annotations

import socket
import sys
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chat_common import recv_line
from server import ChatServer


class WireClient:
    def __init__(self, port: int, nickname: str, password: str | None = None):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=2)
        self.sock.settimeout(2)
        first = recv_line(self.sock)
        if first == "NEED_PW":
            self.send(password or "")
            if recv_line(self.sock) != "OK":
                raise AssertionError("password rejected")
        else:
            assert first == "NO_PW", first
        assert recv_line(self.sock) == "SEND_NICK"
        self.send(nickname)
        self.handshake_result = recv_line(self.sock)
        if self.handshake_result == "OK":
            self.actual_nickname = recv_line(self.sock)
        else:
            self.actual_nickname = ""

    def send(self, text: str) -> None:
        self.sock.sendall((text + "\n").encode("utf-8"))

    def receive_until(self, fragment: str, limit: int = 30) -> list[str]:
        lines = []
        for _ in range(limit):
            line = recv_line(self.sock)
            lines.append(line)
            if fragment in line:
                return lines
        raise AssertionError(f"did not receive {fragment!r}: {lines!r}")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class ChatServerIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ChatServer(host="127.0.0.1", port=0, enable_broadcast=False)
        self.server.start()
        self.clients: list[WireClient] = []

    def tearDown(self) -> None:
        for client in self.clients:
            client.close()
        self.server.stop()

    def connect(self, nickname: str) -> WireClient:
        client = WireClient(self.server.port, nickname)
        self.clients.append(client)
        return client

    def test_handshake_chat_room_and_updown_game(self) -> None:
        alice = self.connect("앨리스")
        self.assertEqual("OK", alice.handshake_result)
        self.assertEqual("NICK:앨리스", alice.actual_nickname)

        bob = self.connect("Bob")
        self.assertEqual("OK", bob.handshake_result)
        alice.receive_until("Bob 입장")

        alice.send("안녕하세요")
        self.assertIn("[앨리스] 안녕하세요", bob.receive_until("안녕하세요"))

        alice.send("//mgr 2 범위찾기")
        alice.receive_until("개설 완료")
        bob.send("//join 1")
        bob.receive_until("Bob 참가")

        alice.send("//start")
        alice.receive_until("GAME_START:updown")
        bob.receive_until("GAME_START:updown")

        deadline = time.time() + 2
        game = None
        while time.time() < deadline:
            game = self.server.rooms[1].game
            if game is not None:
                break
            time.sleep(0.01)
        self.assertIsNotNone(game)
        game.answer = 50
        alice.send("GAME_INPUT:50")
        alice.receive_until("GAME_END")
        bob.receive_until("GAME_END")
        self.assertIsNone(self.server.rooms[1].game)

    def test_duplicate_and_invalid_nicknames_are_rejected(self) -> None:
        first = self.connect("SameNick")
        self.assertEqual("OK", first.handshake_result)
        duplicate = self.connect("samenick")
        self.assertTrue(duplicate.handshake_result.startswith("ERR:NICK:"))

        invalid = self.connect("bad nick")
        self.assertTrue(invalid.handshake_result.startswith("ERR:NICK:"))

    def test_password_and_message_length_validation(self) -> None:
        self.server.stop()
        self.server = ChatServer(
            host="127.0.0.1", port=0, password="pw", enable_broadcast=False
        )
        self.server.start()
        client = WireClient(self.server.port, "Tester", password="pw")
        self.clients.append(client)
        self.assertEqual("OK", client.handshake_result)

        client.send("가" * 301)
        client.receive_until("300자 이하여야 합니다")


if __name__ == "__main__":
    unittest.main(verbosity=2)
