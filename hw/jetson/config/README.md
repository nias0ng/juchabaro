# 구역 정의

메인 배포와 Pipeline Viewer는 `zone_definition.json` version 2를 정본으로
사용한다. 이 파일은 pilot 물리 구역을 crop하지 않은 full-frame 좌표계로
복원하고 명시적 EXIT 기준선을 포함한 snapshot이다.

`zone_definition.pilot.json` version 7은 좌측 150px crop을 적용하는
`CropFrameSource`, `replay_pilot_video.py`, `watch_live_stream.py` 전용이다.
두 파일을 서로 바꿔 사용하면 정규화된 x좌표와 실제 frame 폭이 어긋난다.

`zone_definition.json`은 `스크린샷 2026-08-03 오후 7.20.12.png`의
카메라 영상 구간(3024×1702)에 `camera_calibration.json`과
`remap balance=0.5`를 적용한 frame을 기준으로 잡은 배포 설정이다. 원본
스크린샷의 위·아래 검은 레터박스는 remap 전에 제외했다. 좌표는
보정 frame 너비와 높이로 나눈 0~1 정규화 값이다.
version 1의 꼭짓점은 crop 도입 전 `zone_definition.pilot.json` version 5의
full-frame 폴리곤을 그대로 복원한다.

`camera_calibration.json`은 `ai/tracking/camera_calibration.json`과 같은
캘리브레이션 수치를 가진 운영 배포용 복사본이다. Viewer·live·replay는 기존
`ai/tracking` 경로를 계속 사용한다. 두 파일의 JSON 수치가 달라지면 안 되며,
운영 파일의 원시 바이트 SHA-256 앞 16자리와 이 디렉터리 snapshot들의
`calibrationReference`가 일치해야 한다.

| zoneId | 임시 위치 | zoneType | entryExitRole |
|---:|---|---|---|
| 1 | 왼쪽 위 주차면 | `GENERAL` | - |
| 2 | 왼쪽 가운데 주차면 | `GENERAL` | - |
| 3 | 왼쪽 아래 주차면 | `GENERAL` | - |
| 4 | 오른쪽 위 장애인면 | `DISABLED` | - |
| 5 | 오른쪽 가운데 전기차면 | `EV_CHARGING` | - |
| 6 | 오른쪽 아래 주차면 | `GENERAL` | - |
| 7 | 두 주차열 사이와 입·출구 사이의 중앙 통로 | `AISLE` | - |
| 8 | 왼쪽 위 입구 | `ENTRY_EXIT` | `ENTRY` |
| 9 | 오른쪽 위 출구 | `ENTRY_EXIT` | `EXIT` |

zone 5의 `allowedDurationSeconds=70`은 EV_OVERSTAY OPEN·증거·RESOLVE를
현장 시연 시간 안에 검증하기 위한 provisional 값이다. 법령 또는 운영 정책으로
확정한 허용시간이 아니며, 실제 운영 배포 전 Backend 정책과 합의한 값으로
교체하고 `zoneDefinitionVersion` 변경 여부를 함께 검토한다.

입구와 출구는 같은 `ENTRY_EXIT` ZoneType을 유지하고 `entryExitRole` 값으로
구분한다. `ENTRY_EXIT`에는 `ENTRY` 또는 `EXIT`가 반드시 필요하며, 다른
ZoneType에는 이 필드를 두지 않는다. 입차 attempt는 `ENTRY` 구역에서만 물리
매칭한다. 입구·출구 polygon은 보정 frame에서 검은 바닥의 외곽과 관측 가능한
구분선·가림막 모서리에 맞췄다. 출구는 오른쪽 위 검은 바닥 꼭짓점을 포함하며,
입구 왼쪽 변은 왼쪽 위 바닥 꼭짓점과 가림막 하단에서 보이는 바닥 모서리를
잇는다. fisheye 보정 후에도 카메라 원근은 남으므로 frame에서는 사다리꼴로
보인다.

`EXIT` role의 `ENTRY_EXIT`은 `exitTraversal` object를 반드시 갖는다.
`line`은 통과 기준선의 정규화 좌표 두 점, `outwardPoint`는
외향 측을 고정하는 정규화 점, `hysteresis`는 기준선 근처
jitter를 억제하는 정규화 거리다. `ENTRY` role과 다른 ZoneType에는
`exitTraversal`을 두지 않는다. 인접 AISLE 중심에서 외향을 자동
유도하지 않는다. 배포 `hysteresis=0.01`은 provisional이며 실제
bbox 중심 흔들림을 측정한 뒤 version을 올려 재조정한다.

## 이중주차 egress aisle

`egress_aisle.json`은 메인 `zone_definition.json` version 2와 같은
full-frame 좌표계를 사용한다. `egress_aisle.pilot.json`은
`zone_definition.pilot.json` version 7과 같은 좌측 150px crop 좌표계다.
메인·Viewer에는 전자를, crop을 켠 replay·live 스크립트에는 후자를
사용해야 한다. 두 파일은 주차면 1~6의 같은 물리 출차 공간을
각 좌표계로 표현한 별도 snapshot이다.

`areas`는 Viewer overlay, side mask, ZoneVisit, `AISLE_BLOCK`에 포함되지
않고 `BlockingRelation` geometry에만 사용한다.

현재 polygon은 각 주차면의 복도 방향 면을 기준으로 연장한 파일럿
초기값이다. 운영 임계값과 함께 실제 영상으로 재조정해야 하며,
수정할 때는 다음 계약을 유지한다.

- `zoneDefinitionVersion`은 참조하는 Zone snapshot과 같아야 한다.
- `calibrationReference`는 Zone snapshot과 정확히 같아야 한다.
- `egressZoneId`는 기존 durable/API 식별자 명칭을 보존하지만,
  `zone_definition` namespace가 아니라 이 파일 안에서 유일한 ID다.
- `parkingZoneId`는 `GENERAL / DISABLED / EV_CHARGING` 주차면만
  참조할 수 있다.
