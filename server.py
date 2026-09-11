"""Threaded LAN chat server compatible with ``client.pyw``.

The original project already contained the client UI and six server-side game
classes, but the process that accepted clients and connected those pieces was
missing.  This module supplies that integration layer without changing the
existing client or game rules.
"""

from __future__ import annotations

import argparse
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from chat_common import MAX_MESSAGE_LEN, MAX_NICKNAME_LEN, recv_line
from games.initial import InitialQuiz
from games.liar import LiarGame
from games.ox_quiz import OXQuiz
from games.rps import RockPaperScissors
from games.updown import UpDown
from games.wordchain import WordChain


GAME_TYPES = {
    "1": RockPaperScissors,
    "2": UpDown,
    "3": WordChain,
    "4": InitialQuiz,
    "5": OXQuiz,
    "6": LiarGame,
}

NICKNAME_RE = re.compile(r"^[0-9A-Za-z_\-가-힣]+$")


@dataclass
class ClientSession:
    sock: socket.socket
    address: tuple[str, int]
    nickname: str
    room_id: Optional[int] = None
    send_lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class GameRoom:
    room_id: int
    game_number: str
    name: str
    owner: socket.socket
    members: list[socket.socket] = field(default_factory=list)
    game: object | None = None

    @property
    def started(self) -> bool:
        return self.game is not None and bool(getattr(self.game, "started", False))


class ChatServer:
    """TCP chat server with UDP discovery and game-room coordination."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5000,
        broadcast_port: int = 5001,
        password: str | None = None,
        max_clients: int = 50,
        enable_broadcast: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.broadcast_port = broadcast_port
        self.password = password
        self.max_clients = max_clients
        self.enable_broadcast = enable_broadcast

        self._listener: socket.socket | None = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._threads: list[threading.Thread] = []
        self._sessions: Dict[socket.socket, ClientSession] = {}
        self._rooms: Dict[int, GameRoom] = {}
        self._next_room_id = 1
        self._banned_ips: set[str] = set()

    @property
    def sessions(self) -> dict[socket.socket, ClientSession]:
        with self._lock:
            return dict(self._sessions)

    @property
    def rooms(self) -> dict[int, GameRoom]:
        with self._lock:
            return dict(self._rooms)

    def start(self) -> None:
        """Bind the listener and start accepting clients in background threads."""
        if self._listener is not None:
            raise RuntimeError("server already started")

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self.port))
        listener.listen()
        listener.settimeout(0.25)
        self._listener = listener
        self.port = listener.getsockname()[1]

        accept_thread = threading.Thread(target=self._accept_loop, name="lan-chat-accept", daemon=True)
        accept_thread.start()
        self._threads.append(accept_thread)

        if self.enable_broadcast:
            broadcast_thread = threading.Thread(
                target=self._broadcast_loop,
                name="lan-chat-discovery",
                daemon=True,
            )
            broadcast_thread.start()
            self._threads.append(broadcast_thread)

    def serve_forever(self) -> None:
        self.start()
        try:
            while not self._stop_event.wait(0.5):
                pass
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop accepting connections and close every active client socket."""
        if self._stop_event.is_set():
            return
        self._stop_event.set()

        listener = self._listener
        self._listener = None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass

        with self._lock:
            sockets = list(self._sessions)
        for sock in sockets:
            self._close_socket(sock)

        current = threading.current_thread()
        for thread in list(self._threads):
            if thread is not current:
                thread.join(timeout=1.0)

    def ban_ip(self, ip: str) -> None:
        """Block an address and disconnect current sessions from it."""
        with self._lock:
            self._banned_ips.add(ip)
            sockets = [s.sock for s in self._sessions.values() if s.address[0] == ip]
        for sock in sockets:
            self._disconnect(sock)

    def _accept_loop(self) -> None:
        while not self._stop_event.is_set():
            listener = self._listener
            if listener is None:
                return
            try:
                sock, address = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            thread = threading.Thread(
                target=self._client_worker,
                args=(sock, address),
                name=f"lan-chat-client-{address[0]}:{address[1]}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def _broadcast_loop(self) -> None:
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            while not self._stop_event.wait(1.0):
                try:
                    udp.sendto(b"LAN_CHAT_SERVER", ("255.255.255.255", self.broadcast_port))
                except OSError:
                    if self._stop_event.is_set():
                        return
        finally:
            udp.close()

    def _client_worker(self, sock: socket.socket, address: tuple[str, int]) -> None:
        try:
            session = self._handshake(sock, address)
            if session is None:
                return
            self._broadcast(f"[공지] {session.nickname} 입장")

            while not self._stop_event.is_set():
                message = recv_line(sock)
                if not message:
                    return
                self._handle_message(session, message)
        except (ConnectionError, OSError, UnicodeError, ValueError):
            pass
        finally:
            self._disconnect(sock)

    def _handshake(
        self, sock: socket.socket, address: tuple[str, int]
    ) -> ClientSession | None:
        sock.settimeout(10)
        with self._lock:
            if address[0] in self._banned_ips:
                self._send_line(sock, "ERR:BANNED")
                return None
            if len(self._sessions) >= self.max_clients:
                self._send_line(sock, "ERR:FULL")
                return None

        if self.password:
            self._send_line(sock, "NEED_PW")
            supplied = recv_line(sock)
            if supplied != self.password:
                self._send_line(sock, "ERR")
                return None
            self._send_line(sock, "OK")
        else:
            self._send_line(sock, "NO_PW")

        self._send_line(sock, "SEND_NICK")
        nickname = recv_line(sock)
        error = self._nickname_error(nickname)
        with self._lock:
            duplicate = any(s.nickname.casefold() == nickname.casefold() for s in self._sessions.values())
        if duplicate:
            error = "이미 사용 중인 닉네임"
        if error:
            self._send_line(sock, f"ERR:NICK:{error}")
            return None

        session = ClientSession(sock=sock, address=address, nickname=nickname)
        with self._lock:
            self._sessions[sock] = session
        sock.settimeout(None)
        self._send_to(sock, "OK")
        self._send_to(sock, f"NICK:{nickname}")
        return session

    @staticmethod
    def _nickname_error(nickname: str) -> str | None:
        if not nickname:
            return "닉네임을 입력하세요"
        if len(nickname) > MAX_NICKNAME_LEN:
            return f"{MAX_NICKNAME_LEN}자 이하여야 합니다"
        if not NICKNAME_RE.fullmatch(nickname):
            return "한글/영문/숫자/_/-만 사용할 수 있습니다"
        return None

    def _handle_message(self, session: ClientSession, message: str) -> None:
        if len(message) > MAX_MESSAGE_LEN:
            self._send_to(session.sock, f"메시지는 {MAX_MESSAGE_LEN}자 이하여야 합니다")
            return
        if message.startswith("//"):
            self._handle_command(session, message)
            return

        room = self._room_for(session)
        if room and room.started and message.startswith("GAME_INPUT:"):
            room.game.on_message(session.sock, session.nickname, message)
            return
        self._broadcast(f"[{session.nickname}] {message}")

    def _handle_command(self, session: ClientSession, message: str) -> None:
        parts = message.split(maxsplit=2)
        command = parts[0].casefold()

        if command == "//users":
            names = sorted(s.nickname for s in self.sessions.values())
            self._send_to(session.sock, f"현재 접속자 ({len(names)}명): {', '.join(names)}")
        elif command == "//list":
            self._send_room_list(session.sock)
        elif command == "//mgr":
            if len(parts) < 2:
                self._send_to(session.sock, "명령어: //mgr 게임번호 [방 이름]")
            else:
                self._create_room(session, parts[1], parts[2] if len(parts) > 2 else "")
        elif command == "//join":
            if len(parts) < 2 or not parts[1].isdigit():
                self._send_to(session.sock, "명령어: //join 방번호")
            else:
                self._join_room(session, int(parts[1]))
        elif command == "//leave":
            self._leave_room(session)
        elif command == "//start":
            self._start_game(session)
        elif command == "//stop":
            self._stop_game(session)
        elif command == "//help":
            self._send_to(
                session.sock,
                "명령어: //users, //list, //mgr 게임번호 [방 이름], //join 방번호, "
                "//leave, //start, //stop",
            )
        else:
            self._send_to(session.sock, "알 수 없는 명령어입니다. //help를 입력하세요")

    def _create_room(self, session: ClientSession, game_number: str, name: str) -> None:
        if game_number not in GAME_TYPES:
            self._send_to(session.sock, "게임 번호는 1~6 중 하나여야 합니다")
            return
        if session.room_id is not None:
            self._send_to(session.sock, "이미 참가 중인 방이 있습니다")
            return
        with self._lock:
            room_id = self._next_room_id
            self._next_room_id += 1
            room = GameRoom(
                room_id=room_id,
                game_number=game_number,
                name=(name.strip() or f"{GAME_TYPES[game_number].NAME} 방")[:30],
                owner=session.sock,
                members=[session.sock],
            )
            self._rooms[room_id] = room
            session.room_id = room_id
        self._send_to(session.sock, f"[방{room_id}] 개설 완료: {room.name}")

    def _join_room(self, session: ClientSession, room_id: int) -> None:
        if session.room_id is not None:
            self._send_to(session.sock, "먼저 현재 방에서 나가세요")
            return
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                self._send_to(session.sock, "존재하지 않는 방입니다")
                return
            if room.started:
                self._send_to(session.sock, "이미 게임이 시작된 방입니다")
                return
            if len(room.members) >= GAME_TYPES[room.game_number].MAX_PLAYERS:
                self._send_to(session.sock, "게임 방 정원이 가득 찼습니다")
                return
            room.members.append(session.sock)
            session.room_id = room_id
        self._room_broadcast(room, f"[방{room_id}] {session.nickname} 참가")

    def _leave_room(self, session: ClientSession, disconnected: bool = False) -> None:
        room = self._room_for(session)
        if room is None:
            if not disconnected:
                self._send_to(session.sock, "참가 중인 방이 없습니다")
            return

        if room.started and room.game is not None:
            room.game.remove_player(session.sock)
        with self._lock:
            if session.sock in room.members:
                room.members.remove(session.sock)
            session.room_id = None
            if not room.members:
                self._rooms.pop(room.room_id, None)
                return
            if room.owner == session.sock:
                room.owner = room.members[0]
                new_owner = self._sessions.get(room.owner)
            else:
                new_owner = None
        if not disconnected:
            self._send_to(session.sock, f"[방{room.room_id}] 나가기 완료")
        self._room_broadcast(room, f"[방{room.room_id}] {session.nickname} 퇴장")
        if new_owner:
            self._room_broadcast(room, f"새 방장: {new_owner.nickname}")

    def _start_game(self, session: ClientSession) -> None:
        room = self._room_for(session)
        if room is None:
            self._send_to(session.sock, "참가 중인 방이 없습니다")
            return
        if room.owner != session.sock:
            self._send_to(session.sock, "방장만 게임을 시작할 수 있습니다")
            return
        if room.started:
            self._send_to(session.sock, "이미 게임이 시작됐습니다")
            return

        game_type = GAME_TYPES[room.game_number]
        members = [self._sessions[s] for s in room.members if s in self._sessions]
        if len(members) < game_type.MIN_PLAYERS:
            self._send_to(session.sock, f"최소 {game_type.MIN_PLAYERS}명이 필요합니다")
            return

        game = game_type(
            self._broadcast,
            self._send_to,
            lambda rid=room.room_id: self._end_game(rid),
        )
        for member in members:
            ok, reason = game.add_player(member.sock, member.nickname)
            if not ok:
                self._send_to(session.sock, f"게임 준비 실패: {reason}")
                return
        with self._lock:
            room.game = game
        game.start()

    def _stop_game(self, session: ClientSession) -> None:
        room = self._room_for(session)
        if room is None or not room.started:
            self._send_to(session.sock, "진행 중인 게임이 없습니다")
            return
        if room.owner != session.sock:
            self._send_to(session.sock, "방장만 게임을 종료할 수 있습니다")
            return
        room.game.notify_end()
        self._room_broadcast(room, "방장이 게임을 종료했습니다")
        self._end_game(room.room_id)

    def _end_game(self, room_id: int) -> None:
        with self._lock:
            room = self._rooms.get(room_id)
            if room is not None:
                room.game = None

    def _send_room_list(self, sock: socket.socket) -> None:
        with self._lock:
            rooms = list(self._rooms.values())
            sessions = dict(self._sessions)
        if not rooms:
            self._send_to(sock, "현재 개설된 게임 방이 없습니다")
            return
        for room in sorted(rooms, key=lambda r: r.room_id):
            game_type = GAME_TYPES[room.game_number]
            owner = sessions.get(room.owner)
            state = "진행 중" if room.started else "대기"
            owner_name = owner.nickname if owner else "없음"
            self._send_to(
                sock,
                f"[방{room.room_id}] {room.name} | {game_type.NAME} | "
                f"{len(room.members)}/{game_type.MAX_PLAYERS} | 방장 {owner_name} | {state}",
            )

    def _room_for(self, session: ClientSession) -> GameRoom | None:
        if session.room_id is None:
            return None
        with self._lock:
            return self._rooms.get(session.room_id)

    def _room_broadcast(self, room: GameRoom, message: str) -> None:
        for sock in list(room.members):
            self._send_to(sock, message)

    def _broadcast(self, message: str) -> None:
        for session in self.sessions.values():
            self._send_to(session.sock, message)

    @staticmethod
    def _send_line(sock: socket.socket, message: str) -> None:
        sock.sendall((message.replace("\n", " ") + "\n").encode("utf-8"))

    def _send_to(self, sock: socket.socket, message: str) -> None:
        with self._lock:
            session = self._sessions.get(sock)
        try:
            if session is None:
                self._send_line(sock, message)
            else:
                with session.send_lock:
                    self._send_line(sock, message)
        except OSError:
            self._disconnect(sock)

    def _disconnect(self, sock: socket.socket) -> None:
        with self._lock:
            session = self._sessions.pop(sock, None)
        if session is None:
            self._close_socket(sock)
            return
        self._leave_room(session, disconnected=True)
        self._close_socket(sock)
        self._broadcast(f"[공지] {session.nickname} 퇴장")

    @staticmethod
    def _close_socket(sock: socket.socket) -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LAN 채팅·미니게임 서버")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--broadcast-port", type=int, default=5001)
    parser.add_argument("--password")
    parser.add_argument("--max-clients", type=int, default=50)
    parser.add_argument("--no-broadcast", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ChatServer(
        host=args.host,
        port=args.port,
        broadcast_port=args.broadcast_port,
        password=args.password,
        max_clients=args.max_clients,
        enable_broadcast=not args.no_broadcast,
    )
    print(f"LAN 채팅 서버 시작: {args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
