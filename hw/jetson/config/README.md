# Pilot 구역 정의

`zone_definition.pilot.json`은 `task14_video3_0335000ms.png`의 왜곡 보정된
1920×1080 frame을 기준으로 잡은 임시 배포 설정이다. 좌표는 frame 너비와
높이로 나눈 0~1 정규화 값이다.

| zoneId | 임시 위치 | zoneType |
|---:|---|---|
| 1 | 왼쪽 위 전기차면 | `EV_CHARGING` |
| 2 | 왼쪽 가운데 주차면 | `GENERAL` |
| 3 | 왼쪽 아래 주차면 | `GENERAL` |
| 4 | 오른쪽 위 장애인면 | `DISABLED` |
| 5 | 오른쪽 가운데 주차면 | `GENERAL` |
| 6 | 오른쪽 아래 주차면 | `GENERAL` |
| 7 | 두 주차열 사이 중앙 통로 | `AISLE` |
| 8 | 오른쪽 위 복도의 왼쪽 절반, 임시 입구 | `ENTRY_EXIT` |
| 9 | 오른쪽 위 복도의 오른쪽 절반, 임시 출구 | `ENTRY_EXIT` |

현재 도메인 계약은 입구와 출구를 별도 ZoneType으로 나누지 않으므로 8과 9는
모두 `ENTRY_EXIT`이다. 방향 의미는 zoneId 설명에만 있으며 아직 판정 코드가
해석하지 않는다. 입출구 벽을 설치하고 같은 calibration으로 기준 frame을 다시
촬영한 뒤 두 polygon을 실제 통로보다 약간 안쪽으로 재조정해야 한다.
