# Pilot 구역 정의

`zone_definition.pilot.json`은 `스크린샷 2026-08-03 오후 7.20.12.png`의
카메라 영상 구간(3024×1702)에 `ai/tracking/camera_calibration.json`과
`remap balance=0.5`를 적용한 frame을 기준으로 잡은 배포 설정이다. 원본
스크린샷의 위·아래 검은 레터박스는 remap 전에 제외했다. 좌표는
보정 frame 너비와 높이로 나눈 0~1 정규화 값이다.

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

입구와 출구는 같은 `ENTRY_EXIT` ZoneType을 유지하고 `entryExitRole` 값으로
구분한다. `ENTRY_EXIT`에는 `ENTRY` 또는 `EXIT`가 반드시 필요하며, 다른
ZoneType에는 이 필드를 두지 않는다. 입차 attempt는 `ENTRY` 구역에서만 물리
매칭한다. 입구·출구 polygon은 보정 frame에서 검은 바닥의 외곽과 관측 가능한
구분선·가림막 모서리에 맞췄다. 출구는 오른쪽 위 검은 바닥 꼭짓점을 포함하며,
입구 왼쪽 변은 왼쪽 위 바닥 꼭짓점과 가림막 하단에서 보이는 바닥 모서리를
잇는다. fisheye 보정 후에도 카메라 원근은 남으므로 frame에서는 사다리꼴로
보인다.
