# Game Screen Monitor + Arduino HID Macro

## 1. 프로젝트 목표

게임 화면을 실시간으로 모니터링하고 특정 조건을 만족하면 Arduino HID를 이용하여 키보드 및 마우스 입력을 수행한다.

주요 기능:

* 게임 화면 캡처
* HP 상태 모니터링
* MP 상태 모니터링
* HP/MP 임계값 조건 판단
* Arduino를 통한 키보드 입력
* Arduino를 통한 마우스 이동
* Arduino를 통한 마우스 클릭
* 여러 입력 명령의 안정적인 순차 처리

---

## 2. 기본 구조

```text
Game Screen
     ↓
Screen Capture
     ↓
HP / MP Detector
     ↓
Condition Manager
     ↓
Action Queue
     ↓
Serial
     ↓
Arduino
     ↓
Keyboard / Mouse HID
```

PC는 화면 분석과 조건 판단을 담당한다.

Arduino는 실제 키보드/마우스 HID 입력을 담당한다.

---

## 3. 화면 분석

현재 제공된 게임 화면을 기준으로 화면의 특정 영역(ROI)을 설정하여 HP와 MP를 감지한다.

초기 구현은 전체 화면을 분석하지 말고 필요한 영역만 ROI로 잘라서 처리한다.

예:

```text
HP ROI
MP ROI
```

HP/MP 감지는 우선 OpenCV 기반 색상/픽셀 분석을 사용한다.

필요할 경우 OCR을 추가한다.

화면 해상도나 UI 위치가 변경될 수 있으므로 ROI 좌표는 설정 파일에서 변경 가능하도록 한다.

---

## 4. HP 조건

사용자가 HP 임계값을 설정할 수 있어야 한다.

예:

```text
HP <= 30%
→ 지정된 키 입력
```

예를 들어:

```text
HP 30% 이하
→ F1 입력
```

조건이 계속 유지되는 동안 매 프레임마다 F1을 반복해서 보내지 않는다.

Trigger Cooldown 또는 상태 변화 감지를 사용한다.

---

## 5. MP 조건

MP도 동일하게 처리한다.

예:

```text
MP <= 20%
→ F2 입력
```

HP와 MP 조건은 서로 독립적으로 동작해야 한다.

---

## 6. Arduino 입력

Arduino는 USB HID를 이용하여 다음 기능을 제공한다.

### Keyboard

* Key Down
* Key Up
* Single Key
* Double Key

### Mouse

* Mouse Move
* Left Click
* Right Click
* Middle Click

마우스 이동은 가능하면 절대좌표 기반 입력을 지원한다.

단, 사용하는 Arduino 보드의 USB HID 방식이 상대좌표만 지원하는 경우 보드 특성에 맞는 별도 구현 방법을 검토한다.

---

## 7. 입력 Queue

여러 입력이 동시에 요청되어도 명령이 유실되지 않도록 Queue를 사용한다.

예:

```text
HP 조건
 ↓
F1

동시에

MP 조건
 ↓
F2

Queue:

[F1]
[F2]
```

Arduino에서도 수신한 명령을 Queue에 저장한 후 순차적으로 실행한다.

입력 명령을 단일 `currentCommand` 변수에 덮어쓰는 방식은 사용하지 않는다.

---

## 8. Non-blocking

Arduino Scheduler는 반드시 `millis()` 기반으로 구현한다.

다음과 같은 blocking 방식은 사용하지 않는다.

```cpp
delay();
```

Serial 수신도 blocking 방식으로 구현하지 않는다.

화면 감지, Serial 통신, Scheduler가 서로의 실행을 막지 않아야 한다.

---

## 9. Action Sequence

하나의 조건에 여러 입력이 필요한 경우 Sequence로 관리한다.

예:

```text
HP <= 30%

→ Mouse Move
→ Left Click
→ F1
→ F2
```

이를 하나의 Action Sequence로 만들어 Queue에 넣는다.

각 이벤트 사이의 시간도 설정할 수 있도록 한다.

예:

```text
MOVE
WAIT 30ms
CLICK
WAIT 50ms
F1
WAIT 100ms
F2
```

---

## 10. Serial Protocol

PC와 Arduino 사이에는 명확한 Serial Protocol을 사용한다.

명령에는 가능하면 Sequence ID를 포함한다.

예:

```text
CMD 100 KEY F1
CMD 101 MOUSE_MOVE 500 300
CMD 102 MOUSE_CLICK LEFT
```

Arduino는 처리 결과를 ACK 또는 상태 응답으로 반환할 수 있도록 설계한다.

---

## 11. 안전 기능

매크로 STOP 시:

```text
Queue Clear
↓
Release All Keys
↓
Release All Mouse Buttons
↓
Scheduler Reset
```

키 또는 마우스 버튼이 눌린 상태로 남지 않아야 한다.

Serial 연결이 끊어지는 경우에도 안전 상태로 전환한다.

---

## 12. 설정

다음 값은 코드에 하드코딩하지 않고 설정 파일 또는 UI에서 변경 가능하도록 한다.

* HP ROI
* MP ROI
* HP 임계값
* MP 임계값
* Trigger Cooldown
* 키 입력
* 마우스 좌표
* 클릭 종류
* 입력 간격

---

## 13. 권장 프로젝트 구조

```text
project/
├── AGENTS.md
├── pc/
│   ├── capture/
│   ├── detector/
│   ├── condition/
│   ├── action/
│   ├── queue/
│   ├── serial/
│   └── config/
│
└── arduino/
    ├── scheduler/
    ├── queue/
    ├── serial/
    ├── keyboard/
    ├── mouse/
    └── main.ino
```

---

## 14. 개발 순서

한 번에 전체 프로그램을 구현하지 않는다.

다음 순서로 개발한다.

1. 게임 화면 캡처
2. HP ROI 설정 및 HP 감지
3. MP ROI 설정 및 MP 감지
4. HP/MP 조건 판단
5. Arduino Serial 통신
6. Arduino Keyboard 입력
7. Arduino Mouse 입력
8. Event Queue
9. Action Sequence
10. 전체 통합
11. UI 및 설정 저장

각 단계가 정상적으로 테스트된 후 다음 단계로 진행한다.

---

## 15. Codex 개발 규칙

* 기존 코드를 먼저 분석한 후 수정한다.
* 한 번에 너무 많은 파일을 수정하지 않는다.
* `delay()` 기반 구현을 사용하지 않는다.
* 입력 명령을 덮어쓰지 않는다.
* Queue 기반으로 이벤트를 관리한다.
* 화면 감지와 Arduino 통신 코드를 분리한다.
* HP/MP 감지 좌표를 하드코딩하지 않는다.
* 새로운 기능을 추가할 때 기존 기능을 깨뜨리지 않는다.
* 각 단계마다 테스트 방법을 제시한다.
* 사용자가 확인하기 전에는 다음 단계로 넘어가지 않는다.
