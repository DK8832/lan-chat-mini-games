MAX_MESSAGE_LEN = 300
MAX_NICKNAME_LEN = 12


def recv_line(sock):
    """
    소켓에서 줄바꿈 단위로 한 줄 수신.
    연결 종료 → 빈 문자열
    데이터 초과 / 소켓 오류 → 예외 발생 (호출부에서 처리)
    """
    buf = b""
    while True:
        ch = sock.recv(1)
        if not ch:
            return ""
        if ch == b"\n":
            break
        buf += ch
        if len(buf) > 2048:
            raise ValueError("수신 데이터 초과 (2048바이트)")
    return buf.decode("utf-8", errors="replace").strip()