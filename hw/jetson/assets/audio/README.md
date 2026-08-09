# ToF Warning Audio

Jetson 현장 경고 runtime이 사용하는 WAV 자산이다. 애플리케이션은
`hw/jetson`을 working directory로 실행하며 `.env`의 상대경로로 파일을 찾는다.

| 용도 | 파일 | SHA-256 |
|---|---|---|
| 장애인 전용구역 경고 | `disabled_zone_warning.wav` | `5832ad64289d0ac81431e2867e2d27651b8505198662af0e27b3deabe99d7d9c` |
| 전기차 충전구역 경고 | `ev_zone_warning.wav` | `a6f006cd7638d85d8d42fc0e234fbc63ca0441429e1b624b50cbbed3b87ff17e` |

파일을 교체하면 실제 Jetson의 ALSA device에서 재생을 확인하고 위 지문도 함께
갱신한다. 외부 배포 전에는 음원 제작 및 사용 권한을 별도로 확인한다.
