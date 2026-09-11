import socket
import threading
import tkinter as tk
from tkinter import simpledialog, messagebox
from queue import Queue
from contextlib import suppress
from concurrent.futures import ThreadPoolExecutor, as_completed

from chat_common import recv_line, MAX_MESSAGE_LEN

PORT = 5000
BROADCAST_PORT = 5001
SCAN_TIMEOUT = 0.3

log_queue = Queue()
running = True
client = None
disconnect = None

GAME_LIST = {
    "1": "가위바위보",
    "2": "업다운",
    "3": "끝말잇기",
    "4": "초성퀴즈",
    "5": "OX퀴즈",
    "6": "라이어게임",
}

game_window = None


# ── 서버 탐색 ─────────────────────────────────
def find_server_broadcast(timeout=2):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)
    try:
        sock.bind(("", BROADCAST_PORT))
        data, addr = sock.recvfrom(1024)
        if data == b"LAN_CHAT_SERVER":
            return addr[0]
    except Exception:
        pass
    finally:
        with suppress(Exception):
            sock.close()
    return None


def find_server_scan(set_title):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        my_ip = s.getsockname()[0]
        s.close()
    except Exception:
        try:
            my_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            return None

    parts = my_ip.split(".")
    base = f"{parts[0]}.{parts[1]}"
    third = int(parts[2])
    start = (third // 4) * 4
    ips = [
        f"{base}.{t}.{i}"
        for t in range(start, start + 4)
        for i in range(1, 255)
        if f"{base}.{t}.{i}" != my_ip
    ]
    total = len(ips)
    found_event = threading.Event()
    found_ip = [None]
    done = [0]
    lock = threading.Lock()

    def try_ip(ip):
        if found_event.is_set():
            return
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(SCAN_TIMEOUT)
            s.connect((ip, PORT))
            s.close()
            with lock:
                if found_ip[0] is None:
                    found_ip[0] = ip
            found_event.set()
        except Exception:
            pass
        finally:
            with lock:
                done[0] += 1
            set_title(f"스캔 중... ({done[0]}/{total})")

    with ThreadPoolExecutor(max_workers=60) as ex:
        futs = {ex.submit(try_ip, ip): ip for ip in ips}
        for f in as_completed(futs):
            if found_event.is_set():
                break
            with suppress(Exception):
                f.result()
    return found_ip[0]


def search_server(root_ref):
    result = [None]
    done = threading.Event()

    def set_title(msg):
        with suppress(Exception):
            root_ref.title(msg)

    def run():
        set_title("같은 PC 확인 중...")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect(("127.0.0.1", PORT))
            s.close()
            result[0] = "127.0.0.1"
            set_title("서버 발견: 127.0.0.1")
            done.set()
            return
        except Exception:
            pass
        set_title("브로드캐스트 탐색 중...")
        ip = find_server_broadcast()
        if ip:
            result[0] = ip
            set_title(f"서버 발견: {ip}")
            done.set()
            return
        ip = find_server_scan(set_title)
        result[0] = ip
        set_title(f"서버 발견: {ip}" if ip else "서버를 찾지 못했습니다")
        done.set()

    threading.Thread(target=run, daemon=True).start()
    done.wait()
    return result[0]


# ── 핸드셰이크 ────────────────────────────────
def handshake(server_ip, nickname, root_ref):
    global client
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(5)
    try:
        client.connect((server_ip, PORT))
    except Exception as e:
        with suppress(Exception):
            client.close()
        client = None
        return False, f"연결 실패: {e}"

    success = False
    try:
        resp = recv_line(client)
        if resp == "ERR:FULL":
            return False, "서버가 가득 찼습니다"
        if resp == "ERR:BANNED":
            return False, "이 서버에서 밴됐습니다"
        if resp == "NEED_PW":
            pw = simpledialog.askstring("비밀번호", "서버 비밀번호:", show="*", parent=root_ref)
            if pw is None:
                return False, "취소됨"
            client.sendall((pw.strip() + "\n").encode("utf-8"))
            if recv_line(client) != "OK":
                return False, "비밀번호가 틀렸습니다"
        elif resp != "NO_PW":
            return False, f"알 수 없는 응답: {resp}"
        if recv_line(client) != "SEND_NICK":
            return False, "핸드셰이크 오류"
        client.sendall((nickname + "\n").encode("utf-8"))
        result = recv_line(client)
        if result == "OK":
            # 서버가 실제 닉네임 전송 (노 붙인 경우 등)
            nick_msg = recv_line(client)
            actual_nick = nick_msg[len("NICK:"):] if nick_msg.startswith("NICK:") else nickname
            client.settimeout(None)
            success = True
            return True, actual_nick
        elif result.startswith("ERR:NICK:"):
            return False, f"닉네임 오류: {result[9:]}"
        else:
            return False, f"알 수 없는 응답: {result}"
    except Exception as e:
        return False, f"오류: {e}"
    finally:
        if not success:
            with suppress(Exception):
                client.close()
            client = None


# ════════════════════════════════════════════
# 게임 팝업 UI
# ════════════════════════════════════════════

class BasePopup(tk.Toplevel):
    """모든 게임 팝업의 기반 클래스"""
    def __init__(self, root_ref, title):
        super().__init__(root_ref)
        self.title(title)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", lambda: None)  # 강제 닫기 방지
        self._build_ui()

    def _build_ui(self):
        pass

    def on_server_msg(self, msg):
        """서버 GAME_* 메시지 수신 시 호출"""
        pass

    def send(self, val):
        """서버에 GAME_INPUT:val 전송"""
        send_raw(f"GAME_INPUT:{val}")

    def add_log(self, text):
        if hasattr(self, "log_box"):
            self.log_box.config(state="normal")
            self.log_box.insert(tk.END, text + "\n")
            self.log_box.see(tk.END)
            self.log_box.config(state="disabled")

    def _make_log(self, w=40, h=7):
        box = tk.Text(self, width=w, height=h, state="disabled",
                      font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4", relief="flat")
        box.pack(padx=10, pady=4)
        return box


# ── 가위바위보 팝업 ───────────────────────────
class RpsPopup(BasePopup):
    def __init__(self, root_ref):
        super().__init__(root_ref, "가위바위보")

    def _build_ui(self):
        self.geometry("360x440")
        tk.Label(self, text="가위바위보", font=("", 14, "bold")).pack(pady=(12, 2))

        self.status = tk.Label(self, text="대기 중...", fg="gray", font=("", 10))
        self.status.pack(pady=4)

        self.log_box = self._make_log(42, 7)

        # 판 수 선택 (방장용, 처음엔 숨김)
        self.rounds_frame = tk.Frame(self)
        tk.Label(self.rounds_frame, text="판 수 선택:").pack(side=tk.LEFT, padx=4)
        for r in range(1, 6):
            tk.Button(self.rounds_frame, text=str(r), width=4,
                      command=lambda n=r: self.send(str(n))).pack(side=tk.LEFT, padx=2)

        # 가위/바위/보 버튼 (처음엔 숨김)
        self.pick_frame = tk.Frame(self)
        self.pick_btns = {}
        for choice, emoji in [("가위", "✌"), ("바위", "✊"), ("보", "🖐")]:
            btn = tk.Button(self.pick_frame, text=f"{emoji}\n{choice}",
                            width=7, height=3, font=("", 13),
                            command=lambda c=choice: self._pick(c))
            btn.pack(side=tk.LEFT, padx=8)
            self.pick_btns[choice] = btn

    def _pick(self, choice):
        for btn in self.pick_btns.values():
            btn.config(state="disabled")
        self.send(choice)

    def on_server_msg(self, msg):
        if msg == "GAME_ASK_ROUNDS":
            self.status.config(text="판 수를 선택하세요", fg="#2196f3")
            self.rounds_frame.pack(pady=6)
        elif msg == "GAME_PICK":
            self.rounds_frame.pack_forget()
            for btn in self.pick_btns.values():
                btn.config(state="normal")
            # 중복 pack 방지
            self.pick_frame.pack_forget()
            self.pick_frame.pack(pady=10)
            self.status.config(text="선택하세요!", fg="#4caf50")
        elif "판 진행합니다" in msg:
            self.rounds_frame.pack_forget()
            self.add_log(msg)
            self.status.config(text=msg, fg="gray")
        else:
            self.add_log(msg)
            self.status.config(text=msg[:50], fg="gray")


# ── 업다운 팝업 ───────────────────────────────
class UpDownPopup(BasePopup):
    def __init__(self, root_ref):
        super().__init__(root_ref, "업다운")

    def _build_ui(self):
        self.geometry("320x400")
        tk.Label(self, text="업다운", font=("", 14, "bold")).pack(pady=(12, 2))

        self.status = tk.Label(self, text="대기 중...", fg="gray", font=("", 10))
        self.status.pack(pady=2)

        self.range_label = tk.Label(self, text="범위: 1 ~ 100", font=("", 12))
        self.range_label.pack(pady=4)

        self.log_box = self._make_log(36, 7)

        inp = tk.Frame(self)
        inp.pack(pady=8)
        self.entry = tk.Entry(inp, width=8, font=("", 14), justify="center")
        self.entry.pack(side=tk.LEFT, padx=6)
        self.entry.bind("<Return>", lambda e: self._submit())
        self.submit_btn = tk.Button(inp, text="입력", width=6,
                                    bg="#42a5f5", fg="white",
                                    command=self._submit)
        self.submit_btn.pack(side=tk.LEFT)
        self._set_input(False)

    def _set_input(self, on):
        s = "normal" if on else "disabled"
        self.entry.config(state=s)
        self.submit_btn.config(state=s)
        if on:
            self.entry.focus_set()

    def _submit(self):
        val = self.entry.get().strip()
        if not val.isdigit():
            return
        self.entry.delete(0, tk.END)
        self._set_input(False)
        self.send(val)

    def on_server_msg(self, msg):
        if msg.startswith("GAME_YOUR_TURN:"):
            parts = msg.split(":")
            lo = parts[1] if len(parts) > 1 else "1"
            hi = parts[2] if len(parts) > 2 else "100"
            self.range_label.config(text=f"범위: {lo} ~ {hi}")
            self.status.config(text="당신의 차례!", fg="#4caf50")
            self._set_input(True)
        elif msg == "GAME_WAIT":
            self.status.config(text="상대방 차례...", fg="gray")
            self._set_input(False)
        else:
            self.add_log(msg)
            self.status.config(text=msg[:50], fg="gray")


# ── 끝말잇기 팝업 ─────────────────────────────
class WordChainPopup(BasePopup):
    def __init__(self, root_ref):
        super().__init__(root_ref, "끝말잇기")

    def _build_ui(self):
        self.geometry("340x400")
        tk.Label(self, text="끝말잇기", font=("", 14, "bold")).pack(pady=(12, 2))

        self.status = tk.Label(self, text="대기 중...", fg="gray", font=("", 10))
        self.status.pack(pady=2)

        self.hint = tk.Label(self, text="", font=("", 14, "bold"), fg="#2196f3")
        self.hint.pack(pady=4)

        self.log_box = self._make_log(38, 8)

        inp = tk.Frame(self)
        inp.pack(pady=8)
        self.entry = tk.Entry(inp, width=14, font=("", 12))
        self.entry.pack(side=tk.LEFT, padx=6)
        self.entry.bind("<Return>", lambda e: self._submit())
        self.submit_btn = tk.Button(inp, text="입력", width=6,
                                    bg="#42a5f5", fg="white",
                                    command=self._submit)
        self.submit_btn.pack(side=tk.LEFT)
        self._set_input(False)

    def _set_input(self, on):
        s = "normal" if on else "disabled"
        self.entry.config(state=s)
        self.submit_btn.config(state=s)
        if on:
            self.entry.focus_set()

    def _submit(self):
        val = self.entry.get().strip()
        if not val:
            return
        self.entry.delete(0, tk.END)
        self._set_input(False)
        self.send(val)

    def on_server_msg(self, msg):
        if msg.startswith("GAME_YOUR_TURN:"):
            h = msg.split(":")[1]
            self.hint.config(text=f"「{h}」으로 시작하는 단어" if h else "첫 단어를 입력하세요")
            self.status.config(text="당신의 차례!", fg="#4caf50")
            self._set_input(True)
        elif msg == "GAME_WAIT":
            self.status.config(text="상대방 차례...", fg="gray")
            self._set_input(False)
        elif msg == "GAME_ELIMINATED":
            self.hint.config(text="탈락!", fg="red")
            self._set_input(False)
        else:
            self.add_log(msg)
            self.status.config(text=msg[:50], fg="gray")


# ── 초성퀴즈 팝업 ─────────────────────────────
class InitialPopup(BasePopup):
    def __init__(self, root_ref):
        super().__init__(root_ref, "초성퀴즈")

    def _build_ui(self):
        self.geometry("360x420")
        tk.Label(self, text="초성퀴즈", font=("", 14, "bold")).pack(pady=(12, 2))

        self.progress = tk.Label(self, text="", fg="gray", font=("", 9))
        self.progress.pack()

        self.q_label = tk.Label(self, text="", font=("", 26, "bold"), fg="#2196f3")
        self.q_label.pack(pady=6)

        self.hint_label = tk.Label(self, text="", fg="gray", font=("", 10))
        self.hint_label.pack()

        self.log_box = self._make_log(40, 6)

        inp = tk.Frame(self)
        inp.pack(pady=8)
        self.entry = tk.Entry(inp, width=14, font=("", 12))
        self.entry.pack(side=tk.LEFT, padx=6)
        self.entry.bind("<Return>", lambda e: self._submit())
        tk.Button(inp, text="입력", width=6,
                  bg="#42a5f5", fg="white",
                  command=self._submit).pack(side=tk.LEFT)
        self.entry.focus_set()

    def _submit(self):
        val = self.entry.get().strip()
        if not val:
            return
        self.entry.delete(0, tk.END)
        self.send(val)

    def on_server_msg(self, msg):
        if msg.startswith("GAME_QUESTION:"):
            parts = msg.split(":")
            initial = parts[1] if len(parts) > 1 else ""
            hint    = parts[2] if len(parts) > 2 else ""
            cur     = parts[3] if len(parts) > 3 else ""
            total   = parts[4] if len(parts) > 4 else ""
            self.q_label.config(text=initial)
            self.hint_label.config(text=f"힌트: {hint}")
            self.progress.config(text=f"{cur} / {total} 문제")
            self.entry.focus_set()
        else:
            self.add_log(msg)


# ── OX퀴즈 팝업 ──────────────────────────────
class OXPopup(BasePopup):
    def __init__(self, root_ref):
        super().__init__(root_ref, "OX퀴즈")

    def _build_ui(self):
        self.geometry("380x440")
        tk.Label(self, text="OX퀴즈", font=("", 14, "bold")).pack(pady=(12, 2))

        self.progress = tk.Label(self, text="", fg="gray", font=("", 9))
        self.progress.pack()

        self.q_label = tk.Label(self, text="", font=("", 11),
                                wraplength=340, justify="center")
        self.q_label.pack(pady=10, padx=10)

        self.fb = tk.Label(self, text="", font=("", 10))
        self.fb.pack(pady=2)

        btn_row = tk.Frame(self)
        btn_row.pack(pady=8)
        self.o_btn = tk.Button(btn_row, text="O", font=("", 30, "bold"),
                               width=4, bg="#4caf50", fg="white",
                               command=lambda: self._answer("O"))
        self.o_btn.pack(side=tk.LEFT, padx=16)
        self.x_btn = tk.Button(btn_row, text="X", font=("", 30, "bold"),
                               width=4, bg="#f44336", fg="white",
                               command=lambda: self._answer("X"))
        self.x_btn.pack(side=tk.LEFT, padx=16)

        self.log_box = self._make_log(42, 5)
        self._answered = False

    def _answer(self, val):
        if self._answered:
            return
        self._answered = True
        self.o_btn.config(state="disabled")
        self.x_btn.config(state="disabled")
        self.send(val)

    def on_server_msg(self, msg):
        if msg.startswith("GAME_QUESTION:"):
            parts = msg.split(":")
            q     = parts[1] if len(parts) > 1 else ""
            cur   = parts[2] if len(parts) > 2 else ""
            total = parts[3] if len(parts) > 3 else ""
            self.q_label.config(text=q)
            self.progress.config(text=f"{cur} / {total} 문제")
            self.fb.config(text="O 또는 X를 선택하세요!", fg="#2196f3")
            self._answered = False
            self.o_btn.config(state="normal")
            self.x_btn.config(state="normal")
        elif "정답" in msg and "최종" not in msg:
            self.fb.config(text=msg, fg="#4caf50")
        elif "오답" in msg:
            self.fb.config(text=msg, fg="#f44336")
        else:
            self.add_log(msg)


# ── 라이어게임 팝업 ───────────────────────────
class LiarPopup(BasePopup):
    def __init__(self, root_ref):
        super().__init__(root_ref, "라이어게임")

    def _build_ui(self):
        self.geometry("380x500")
        tk.Label(self, text="라이어게임", font=("", 14, "bold")).pack(pady=(12, 2))

        self.role_lbl = tk.Label(self, text="", font=("", 11, "bold"))
        self.role_lbl.pack(pady=2)
        self.info_lbl = tk.Label(self, text="", fg="gray", font=("", 10))
        self.info_lbl.pack(pady=2)

        self.log_box = self._make_log(42, 8)

        # 설명 입력
        self.desc_frame = tk.Frame(self)
        self.desc_entry = tk.Entry(self.desc_frame, width=20, font=("", 10))
        self.desc_entry.pack(side=tk.LEFT, padx=4)
        self.desc_entry.bind("<Return>", lambda e: self._send_desc())
        tk.Button(self.desc_frame, text="설명", bg="#5c6bc0", fg="white",
                  command=self._send_desc).pack(side=tk.LEFT, padx=2)
        self.vote_start_btn = tk.Button(self.desc_frame, text="투표 시작",
                                        bg="#f44336", fg="white",
                                        command=lambda: self.send("__VOTE__"))
        # 투표 시작 버튼은 방장에게만 노출 (서버 신호로 활성화)
        self.desc_frame.pack(pady=6)
        self._is_host = False

        # 투표 버튼 영역
        self.vote_frame = tk.Frame(self)

        # 마지막 기회 입력
        self.last_frame = tk.Frame(self)
        self.last_entry = tk.Entry(self.last_frame, width=14, font=("", 10))
        self.last_entry.pack(side=tk.LEFT, padx=4)
        self.last_entry.bind("<Return>", lambda e: self._send_last())
        tk.Button(self.last_frame, text="답변", bg="#ff9800", fg="white",
                  command=self._send_last).pack(side=tk.LEFT)

    def _send_desc(self):
        val = self.desc_entry.get().strip()
        if not val:
            return
        self.desc_entry.delete(0, tk.END)
        self.send(val)

    def _send_last(self):
        val = self.last_entry.get().strip()
        if not val:
            return
        self.last_entry.delete(0, tk.END)
        self.send(val)

    def on_server_msg(self, msg):
        if msg.startswith("GAME_ROLE:"):
            parts = msg.split(":")
            role  = parts[1] if len(parts) > 1 else ""
            topic = parts[2] if len(parts) > 2 else ""
            word  = parts[3] if len(parts) > 3 else ""
            if role == "liar":
                self.role_lbl.config(text="당신은 라이어!", fg="#f44336")
                self.info_lbl.config(text=f"주제: {topic}  (단어를 모릅니다)")
            else:
                self.role_lbl.config(text="당신은 시민", fg="#4caf50")
                self.info_lbl.config(text=f"주제: {topic}  /  단어: {word}")
            # 방장에게만 투표 시작 버튼 노출은 서버가 알려줌

        elif msg.startswith("GAME_VOTE:"):
            nicks = msg[len("GAME_VOTE:"):].split(",")
            self.desc_frame.pack_forget()
            for n in nicks:
                tk.Button(self.vote_frame, text=n, width=14,
                          bg="#5c6bc0", fg="white",
                          command=lambda name=n: self._vote(name)).pack(pady=3)
            self.vote_frame.pack(pady=6)

        elif msg == "GAME_LAST_CHANCE":
            self.vote_frame.pack_forget()
            self.info_lbl.config(text="단어를 맞춰보세요!")
            self.last_frame.pack(pady=6)
            self.last_entry.focus_set()

        elif msg == "GAME_HOST":
            self._is_host = True
            self.vote_start_btn.pack(side=tk.LEFT, padx=4)
        elif "투표 버튼" in msg or "방장이 투표" in msg:
            self.add_log(msg)

        else:
            self.add_log(msg)

    def _vote(self, name):
        for btn in self.vote_frame.winfo_children():
            btn.config(state="disabled")
        self.send(name)


# ── 게임 팝업 관리 ────────────────────────────
POPUP_MAP = {
    "rps":       RpsPopup,
    "updown":    UpDownPopup,
    "wordchain": WordChainPopup,
    "initial":   InitialPopup,
    "ox":        OXPopup,
    "liar":      LiarPopup,
}

def open_game_popup(game_key, root_ref):
    global game_window
    if game_window and game_window.winfo_exists():
        return
    cls = POPUP_MAP.get(game_key)
    if cls:
        game_window = cls(root_ref)

def close_game_popup():
    global game_window
    if game_window:
        with suppress(Exception):
            game_window.destroy()
        game_window = None

def dispatch_game_msg(msg):
    if game_window and game_window.winfo_exists():
        # 공통 게임 알림은 전송 구분자인 GAME_MSG:를 제거한 뒤 표시한다.
        # 입력 요청(GAME_PICK, GAME_QUESTION 등)은 팝업이 직접 해석한다.
        if msg.startswith("GAME_MSG:"):
            msg = msg[len("GAME_MSG:"):]
        game_window.on_server_msg(msg)


# ── 게임 관리 팝업 ────────────────────────────
def show_game_popup(root_ref):
    win = tk.Toplevel(root_ref)
    win.title("게임 관리")
    win.resizable(False, False)
    win.geometry("300x400")

    selected = tk.StringVar()
    tk.Label(win, text="게임 선택", font=("", 10, "bold")).pack(pady=(10, 4))
    bf = tk.Frame(win)
    bf.pack(padx=10, fill="x")
    btns = []

    def sel(n):
        selected.set(n)
        for i, b in enumerate(btns):
            b.config(bg="#cce5ff" if str(i + 1) == n else "SystemButtonFace")

    for num, name in GAME_LIST.items():
        b = tk.Button(bf, text=f"[{num}] {name}", width=28, anchor="w",
                      command=lambda n=num: sel(n))
        b.pack(pady=2)
        btns.append(b)

    tk.Label(win, text="방 이름 (생략 가능)", font=("", 9)).pack(pady=(10, 2))
    room_var = tk.StringVar()
    tk.Entry(win, textvariable=room_var, width=28).pack()

    af = tk.Frame(win)
    af.pack(pady=10)

    def create():
        n = selected.get()
        if not n:
            messagebox.showwarning("알림", "게임을 선택하세요", parent=win)
            return
        name = room_var.get().strip()
        send_raw(f"//mgr {n}" + (f" {name}" if name else ""))
        win.destroy()

    def join():
        rid = simpledialog.askstring("방 참가", "참가할 방 번호:", parent=win)
        if rid and rid.isdigit():
            send_raw(f"//join {rid}")
        win.destroy()

    tk.Button(af, text="방 개설",  width=12, bg="#4caf50", fg="white", command=create).grid(row=0, column=0, padx=4, pady=3)
    tk.Button(af, text="방 목록",  width=12, command=lambda: [send_raw("//list"), win.destroy()]).grid(row=0, column=1, padx=4, pady=3)
    tk.Button(af, text="방 참가",  width=12, command=join).grid(row=1, column=0, padx=4, pady=3)
    tk.Button(af, text="방 나가기",width=12, command=lambda: [send_raw("//leave"), win.destroy()]).grid(row=1, column=1, padx=4, pady=3)
    tk.Button(af, text="게임 시작",width=12, bg="#2196f3", fg="white", command=lambda: [send_raw("//start"), win.destroy()]).grid(row=2, column=0, padx=4, pady=3)
    tk.Button(af, text="강제 종료",width=12, bg="#f44336", fg="white", command=lambda: [send_raw("//stop"),  win.destroy()]).grid(row=2, column=1, padx=4, pady=3)
    tk.Button(win, text="닫기", command=win.destroy).pack(pady=(0, 8))


# ── 채팅 로그 ─────────────────────────────────
def add_log(text):
    chat_box.config(state="normal")
    # 메시지 종류별 색상 태그 적용
    if text.startswith("[공지]") or (("밴" in text or "킥" in text) and "[공지]" in text):
        tag = "notice"
    elif "입장" in text or "퇴장" in text:
        tag = "join"
    elif text.startswith("명령어:") or text.startswith("현재 접속자"):
        tag = "system"
    elif re.match(r"^\[방\d+\]", text):
        tag = "system"
    elif "최종 승자" in text or "우승" in text or "정답" in text and "최종" in text:
        tag = "win"
    elif text.startswith("[") and "]" in text:
        tag = "chat"
    else:
        tag = "default"
    chat_box.insert(tk.END, text + "\n", tag)
    chat_box.see(tk.END)
    chat_box.config(state="disabled")

def log(text):
    log_queue.put(text)

def update_log():
    while not log_queue.empty():
        add_log(log_queue.get())
    if running:
        root.after(100, update_log)


# ── 수신 처리 ─────────────────────────────────
def handle_server_msg(msg):
    if msg.startswith("GAME_START:"):
        key = msg[len("GAME_START:"):]
        root.after(0, lambda: open_game_popup(key, root))
    elif msg == "GAME_END":
        root.after(0, close_game_popup)
        log("게임이 종료됐습니다")
    elif msg.startswith("GAME_"):
        root.after(0, lambda m=msg: dispatch_game_msg(m))
    else:
        log(msg)


def make_disconnect(root_ref):
    def _d():
        global running
        if not running:
            return
        running = False
        log("서버 연결이 해제됐습니다")
        root_ref.after(0, lambda: entry.config(state="disabled"))
        root_ref.after(0, lambda: send_btn.config(state="disabled"))
        root_ref.after(0, lambda: game_btn.config(state="disabled"))
    return _d


def receive(disconnect_fn):
    try:
        while running:
            try:
                msg = recv_line(client)
            except (OSError, ValueError) as e:
                log(f"[수신 오류] {e}")
                disconnect_fn()
                break
            if not msg:
                disconnect_fn()
                break
            handle_server_msg(msg)
    except Exception:
        disconnect_fn()


def send_raw(msg):
    if not running or client is None:
        return
    try:
        client.sendall((msg + "\n").encode("utf-8"))
    except Exception:
        if disconnect:
            disconnect()


def send_message(event=None):
    if not running:
        return
    msg = entry.get().strip()
    if not msg:
        return
    if msg == "//game":
        entry.delete(0, tk.END)
        show_game_popup(root)
        return
    if len(msg) > MAX_MESSAGE_LEN:
        log(f"메시지는 {MAX_MESSAGE_LEN}자 이하여야 합니다")
        return
    send_raw(msg)
    entry.delete(0, tk.END)
    char_var.set(f"0 / {MAX_MESSAGE_LEN}")
    char_label.config(fg="gray")


def stop_client():
    global running
    running = False
    close_game_popup()
    if client:
        with suppress(Exception):
            client.shutdown(socket.SHUT_RDWR)
        with suppress(Exception):
            client.close()
    root.destroy()


# ── GUI 초기화 ────────────────────────────────
root = tk.Tk()
root.withdraw()

nickname = simpledialog.askstring(
    "닉네임", "닉네임 입력 (최대 12자, 한글/영문/숫자/_- 허용)", parent=root
)
if not nickname:
    root.destroy()
    raise SystemExit

SERVER_IP = search_server(root)
if not SERVER_IP:
    SERVER_IP = simpledialog.askstring(
        "서버 IP", "자동 탐색 실패. IP를 직접 입력하세요:",
        initialvalue="127.0.0.1", parent=root
    )
    if not SERVER_IP:
        root.destroy()
        raise SystemExit

success, result = handshake(SERVER_IP, nickname, root)
if not success:
    messagebox.showerror("접속 실패", result, parent=root)
    root.destroy()
    raise SystemExit

# result에 실제 닉네임이 담겨 있음
nickname = result

disconnect = make_disconnect(root)

root.deiconify()
root.title(f"LAN 채팅 - {nickname}  |  서버: {SERVER_IP}")
root.configure(bg="#f5f5f5")

chat_box = tk.Text(
    root, width=60, height=20, state="disabled",
    font=("Consolas", 10), bg="#1e1e1e", fg="#d4d4d4",
    insertbackground="white", relief="flat"
)
chat_box.pack(padx=10, pady=10, fill="both", expand=True)

# 메시지 색상 태그 설정
chat_box.tag_config("chat",    foreground="#d4d4d4")
chat_box.tag_config("notice",  foreground="#ff7043", font=("Consolas", 10, "bold"))
chat_box.tag_config("join",    foreground="#66bb6a")
chat_box.tag_config("system",  foreground="#78909c")
chat_box.tag_config("win",     foreground="#ffd54f", font=("Consolas", 10, "bold"))
chat_box.tag_config("default", foreground="#b0bec5")

bottom = tk.Frame(root, bg="#f5f5f5")
bottom.pack(fill="x", padx=10, pady=(0, 8))

game_btn = tk.Button(bottom, text="게임", width=6,
                     bg="#5c6bc0", fg="white", relief="flat",
                     command=lambda: show_game_popup(root))
game_btn.pack(side=tk.LEFT, padx=(0, 4))

tk.Button(bottom, text="접속자", width=6,
          bg="#607d8b", fg="white", relief="flat",
          command=lambda: send_raw("//users")).pack(side=tk.LEFT, padx=(0, 6))

entry = tk.Entry(bottom, width=40, font=("Consolas", 10), relief="flat", bd=2)
entry.pack(side=tk.LEFT, fill="x", expand=True)
entry.bind("<Return>", send_message)

char_var = tk.StringVar(value=f"0 / {MAX_MESSAGE_LEN}")
char_label = tk.Label(bottom, textvariable=char_var, fg="gray",
                      font=("", 8), bg="#f5f5f5")
char_label.pack(side=tk.RIGHT, padx=(4, 0))

send_btn = tk.Button(bottom, text="전송", command=send_message,
                     bg="#42a5f5", fg="white", relief="flat", width=6)
send_btn.pack(side=tk.RIGHT, padx=(4, 0))


def on_key(event=None):
    count = len(entry.get())
    char_var.set(f"{count} / {MAX_MESSAGE_LEN}")
    char_label.config(fg="red" if count > MAX_MESSAGE_LEN else "gray")


entry.bind("<KeyRelease>", on_key)
entry.focus_set()

threading.Thread(target=receive, args=(disconnect,), daemon=True).start()
update_log()

root.protocol("WM_DELETE_WINDOW", stop_client)
root.mainloop()
