# LAN 채팅 및 6종 미니게임

같은 네트워크 안에서 여러 사용자가 채팅하고 게임 방을 만들어 6종 미니게임을 실행할 수 있는 Python 프로젝트다.

## 구성

- `server.py`: TCP 접속, 닉네임 검증, 전체 채팅, 게임 방, 비밀번호, 정원, UDP 자동 탐색을 담당한다.
- `client.pyw`: Tkinter 채팅 UI와 게임별 팝업을 제공한다.
- `chat_common.py`: 줄 단위 UTF-8 프로토콜과 공통 길이 제한을 정의한다.
- `games/`: 가위바위보, 업다운, 끝말잇기, 초성퀴즈, OX퀴즈, 라이어게임 규칙을 분리한다.
- `tests/test_server.py`: 실제 로컬 소켓으로 핸드셰이크, 채팅, 방 참가, 게임 종료, 중복 닉네임, 비밀번호, 길이 제한을 검사한다.

## 실행

```powershell
python server.py
python client.pyw
```

서버 자동 탐색이 되지 않으면 클라이언트 입력창에 서버 PC의 IPv4 주소를 직접 입력한다. 다른 PC에서 접속할 때는 운영체제 방화벽에서 TCP 5000과 UDP 5001의 허용 여부를 확인한다.

비밀번호와 최대 접속자 수를 지정할 수도 있다.

```powershell
python server.py --password example --max-clients 20
```

## 명령어

- `//users`: 현재 접속자 목록
- `//list`: 게임 방 목록
- `//mgr 게임번호 [방 이름]`: 방 개설
- `//join 방번호`: 방 참가
- `//leave`: 방 나가기
- `//start`: 방장이 게임 시작
- `//stop`: 방장이 게임 종료

## 자동 검증

```powershell
python -m unittest discover -s tests -v
```

자동 테스트는 외부 네트워크를 사용하지 않고 `127.0.0.1`의 임시 포트에서 서버와 클라이언트를 함께 실행한다. GUI의 실제 조작감, 여러 실제 PC 사이의 방화벽 통과, 장시간 부하 안정성은 별도 수동 검증이 필요하다.
