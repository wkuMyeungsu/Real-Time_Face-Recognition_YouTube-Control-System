# broker — MQTT 브로커 (Mosquitto)

- 담당: 임우진
- 하는 일: face-detector(ESP32)·playback-decider·player가 주고받는 MQTT 메시지를 중계한다. 메시지 형식은 [docs/contracts/README.md](../../docs/contracts/README.md).
- 이미지: `eclipse-mosquitto:2.0.20` + 설정 [mosquitto.conf](mosquitto.conf) (compose가 읽기 전용으로 붙인다)

## 주소

| 누가 | 주소 | 포트 |
|---|---|---|
| face-detector (ESP32) | `<PC 내부 IP>:1883` | 1883 (호스트에 열림, 같은 Wi-Fi) |
| playback-decider (컨테이너) | `broker:1883` | |
| player (브라우저) | `ws://<페이지 주소>/mqtt` → player(nginx)가 `broker:9001`로 넘김 | 9001 (호스트에 열지 않음) |
| 내 PC의 도구 (`mosquitto_sub`, 가짜 face-detector) | `localhost:1883` | |

1883이 다른 프로그램과 겹치면 `.env`의 `MQTT_PORT`만 바꾼다 (그러면 ESP32 `secrets.h`의 `BROKER_PORT`도 같이).

## 메시지 보기·보내기

```bash
docker compose exec broker mosquitto_sub -v -t 'zt/#'                     # 오가는 메시지 전부
docker compose exec broker mosquitto_sub -v -t 'zt/esp32-a/status'        # 보드 하나의 상태 (retain이라 바로 나옴)
docker compose exec broker mosquitto_pub -t 'zt/esp32-a/control' -m '{"cmd":"start"}'   # 시작 버튼 대신
docker compose logs -f broker                                              # 접속·끊김 기록
```

## retain과 LWT (status가 움직이는 방식)

- `status`는 retain이다. broker가 마지막 값을 기억했다가, 나중에 연 player에도 바로 준다.
- face-detector는 접속할 때 LWT로 `{"state":"offline"}`을 맡긴다. 보드 전원이 꺼지거나 Wi-Fi가 끊기면 broker가 이것을 대신 보낸다.
- LWT는 바로 오지 않는다. broker는 keepalive의 1.5배 동안 아무 신호가 없어야 끊긴 것으로 본다. PubSubClient 기본 keepalive가 15초라 **약 22초 뒤** player에 `offline`이 뜬다. 더 빨리 알려면 face-detector에서 `mqtt.setKeepAlive(5)`(약 8초).
- `persistence false`라 broker를 다시 켜면 retain이 비워진다. 보드가 다시 접속하며 status를 새로 보낸다.

## 안 될 때

**ESP32가 broker에 붙지 않는다** (`[mqtt] 연결됨`이 안 나옴)

1. PC와 보드가 **같은 Wi-Fi**인지. 학교·공용 Wi-Fi는 기기끼리 통신을 막는 경우가 많다 → 휴대폰 핫스팟에 둘 다 붙인다.
2. `secrets.h`의 `BROKER_HOST`가 **PC의 내부 IP**인지 (`ipconfig`의 Wi-Fi IPv4). `localhost`가 아니다. PC IP는 Wi-Fi를 다시 잡으면 바뀔 수 있다.
3. Windows 방화벽 1883 허용 (루트 README의 PowerShell 한 줄).
4. `docker compose ps`에서 broker가 healthy인지, `docker compose logs broker`에 보드의 접속 시도가 찍히는지.

**player에 `offline`이 계속 떴다 사라졌다 한다, 보드가 계속 재접속한다**

보드 두 대가 **같은 `DEVICE_ID`**를 쓰면 이렇게 된다. face-detector는 `DEVICE_ID`를 MQTT 클라이언트 ID로도 쓰는데, broker는 같은 ID가 새로 붙으면 먼저 붙은 쪽을 끊는다 (로그: `Client esp32-a already connected, closing old connection`). 끊긴 쪽의 LWT로 `offline`이 나가고, 끊긴 보드가 다시 붙으며 상대를 끊기를 반복한다. 보드마다 `esp32-a`, `esp32-b`처럼 다르게 한다.

**player의 broker 표시가 `끊김`이다**

player(nginx)의 `/mqtt`가 `broker:9001`로 넘기는지 본다. `docker compose ps`에서 broker와 player가 둘 다 healthy여야 한다.

## 계정 켜기 (공용 Wi-Fi에서 시연할 때만)

지금은 같은 Wi-Fi 안의 누구나 붙을 수 있다. 계정을 켜려면 face-detector·playback-decider·player도 계정을 써야 하므로 팀과 정한 뒤 한다.

```bash
# 비밀번호 파일 만들기 (커밋하지 않는다, .gitignore에 있음)
# broker는 컨테이너 안에서 mosquitto 사용자(1883)로 돌므로 파일 주인을 1883으로 바꿔야 읽을 수 있다
docker run --rm -v "${PWD}/services/broker:/w" eclipse-mosquitto:2.0.20 \
  sh -c "mosquitto_passwd -c -b /w/passwd zt <비밀번호> && chown 1883:1883 /w/passwd"
```

`mosquitto.conf`에서 `allow_anonymous false`, `password_file /mosquitto/config/passwd`로 바꾸고, compose의 broker volumes에 `./services/broker/passwd:/mosquitto/config/passwd:ro`를 더한다.
