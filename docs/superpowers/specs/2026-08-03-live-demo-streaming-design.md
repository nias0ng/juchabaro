# 실시간 데모 시각화(라이브 스트리밍) — 설계

## 배경

시연 때 젯슨이 찍는 영상을 같은 네트워크의 노트북/PC 브라우저로 실시간 송출해, 차량 트래킹과 주차 판단 과정(구역 진입/이탈, 주차 확정)을 시각적으로 보여주고 싶다는 요구에서 시작한다.

지금 레포에는 라이브 스트리밍/시각화 경로가 없다. 참고할 만한 조각은 있지만 그대로 재사용할 수 없다:

- `ai/tracking/replay/overlay.py`의 `OverlayWriter`는 폴리곤·bbox·판정상태를 그리는 방식은 참고할 수 있지만, T-23에서 폐기 예정인 옛 baseline(`jetson_vehicle_tracking_baseline.py`, `VehicleBox`/`TrackSnapshot`/`ViolationStatus`)에 물려 있다. 지금 프로덕션 파이프라인(`hw/jetson/src/application/monitoring_pipeline.py`)은 이미 `ZoneVisit`/`ParkingEpisode` 계약으로 넘어갔으므로, 옛 오버레이를 그대로 배선하면 화면에 그려지는 상태가 실제 판정과 어긋나는 채로 조용히 굳어버린다.
- `MonitoringPipeline.process_next_frame()`은 판정 결과(`FrameObservationResult`)만 반환하고 원본 프레임이나 bbox 픽셀 좌표는 반환하지 않는다. 화면에 그리려면 프레임+bbox가 필요한데, 그리기 목적으로 트래커를 한 번 더 돌리면 젯슨 추론 비용이 거의 2배가 되고, 별도 트래커 인스턴스의 track ID가 판정 쪽과 어긋날 위험도 있다.

## 목표와 범위

- 젯슨 라이브 카메라 → 트래킹 → 주차 판정까지의 실제 프로덕션 파이프라인을 그대로 돌리면서, 같은 프레임에 구역 폴리곤·차량 bbox·트랙ID·판정 상태(ENTERING/INSIDE/EXITING, PARKED 등)를 그려 MJPEG로 브라우저에 실시간 송출한다.
- 대상 시청 환경: 같은 네트워크의 노트북/PC 브라우저, 동시 시청자 소수(데모 부스 기준). WebSocket/WebRTC 같은 고급 스트리밍은 범위 밖 — 데모 목적엔 MJPEG HTTP 스트리밍(`multipart/x-mixed-replace`)으로 충분하고 구현이 가장 빠르다.
- 범위 밖: 클라이언트 측 인터랙션(오버레이 토글 등), 다수 동시 시청자를 위한 확장, 영상 녹화/재생 컨트롤.

## 접근 방식

### 옵저버 훅으로 이중 추론 회피

`MonitoringPipeline.process_next_frame()` 끝(commit 완료 후)에 선택적 콜백 파라미터를 추가한다. 콜백은 `(frame, tracking_batch, result)`를 받는다 — `frame`은 `frame_source.capture()`가 반환한 원본, `tracking_batch`는 이미 내부에서 계산된 bbox/track_id, `result`는 이 프레임 자신의 `FrameObservationResult`(ZoneVisit/ParkingEpisode 갱신 반영 완료 상태)다. 콜백을 넘기지 않으면 기존 replay 경로(`replay_pilot_video.py`, 관련 결정론 테스트)는 완전히 그대로 동작한다 — 추가 분기 하나, 오버헤드 0.

이 훅 하나로 "화면에 그리는 판정 상태"와 "실제 커밋된 판정 상태"가 항상 같은 프레임·같은 추론 결과에서 나오는 것을 보장한다.

### 라이브 캡처 루프

`replay_pilot_video.py`가 조립하는 것과 같은 프로덕션 컴포넌트(`RemapFrameSource`, `UltralyticsVehicleTracker`, `build_monitoring_pipeline`)를 재사용하되, `VideoFileFrameSource` 대신 `OpenCvWebcamFrameSource`를 프레임 소스로 쓴다. 이 루프는 FastAPI의 비동기 이벤트 루프를 막지 않도록 별도 백그라운드 스레드에서 돈다.

리허설(카메라 없이 파일럿 영상으로 전체 경로 미리 검증)을 위해, 프레임 소스를 `VideoFileFrameSource`로 바꿔서도 같은 루프를 돌릴 수 있게 만든다 — 별도 코드가 아니라 같은 라이브 루프에 다른 `FrameSource` 구현을 주입하는 것으로 해결한다.

### 렌더링과 스트리밍

옵저버 콜백이 받은 `(frame, tracking_batch, result)`로 프레임 위에 존 폴리곤(`ZoneRegistry` 재사용)·bbox·트랙ID·`ZoneVisit.state`/`ParkingEpisode.state` 기반 색상 오버레이를 그려 JPEG로 인코딩한다. 그리는 방식은 `OverlayWriter`를 참고하되, 데이터 소스는 새 계약(ZoneVisit/ParkingEpisode)에서 가져온다.

인코딩된 최신 JPEG 1장을 스레드 세이프한 단일 슬롯 버퍼에 계속 덮어쓴다. FastAPI에 새 GET 엔드포인트(`/live/stream`)를 추가해 그 버퍼를 `multipart/x-mixed-replace`로 스트리밍한다. 여러 브라우저 탭이 붙어도 각자 독립된 응답 제너레이터가 같은 버퍼를 읽기만 하므로 추가 부하가 거의 없다. 프레임레이트는 원본 fps와 15fps 중 낮은 쪽으로 캡해 인코딩/전송 부하가 캡처·추론 루프를 밀어내지 않게 한다.

## 컴포넌트

1. **`MonitoringPipeline` 옵저버 훅 추가** (기존 파일 수정) — `process_next_frame()`에 선택적 `on_frame_observed` 콜백 파라미터 추가.
2. **`src/live/live_overlay_renderer.py`(신규)** — `(frame, tracking_batch, result)` → 오버레이가 그려진 JPEG bytes. 순수 함수에 가깝게 만들어 카메라 없이도 유닛테스트 가능하게 한다.
3. **`src/live/live_stream_loop.py`(신규)** — 캡처→추적→판정 루프를 백그라운드 스레드에서 실행, 렌더러 호출, 결과를 공유 버퍼에 게시. `FrameSource` 구현체를 주입받아 라이브 카메라/파일럿 영상 리허설 양쪽에 쓴다.
4. **`src/api/live_stream_router.py`(신규)** — `GET /live/stream` MJPEG 엔드포인트. 편의를 위해 `<img>` 태그 하나짜리 정적 HTML을 `/live`에 같이 서빙한다.

## 에러 처리

- 카메라 연결 끊김(`FrameSourceError`): 루프가 잡아 로그를 남기고, 공유 버퍼에 "연결 끊김" 플레이스홀더 프레임을 넣어 브라우저가 마지막 프레임에 멈춰 있는 것처럼 보이지 않게 한 뒤, 백오프 후 재연결을 시도한다.
- 브라우저 탭 종료: Starlette이 해당 스트림 제너레이터를 정리한다. 캡처 루프 자체는 시청자 유무와 무관하게 계속 돈다.
- 리플레이(영상 파일) 모드에서 `EndOfVideo`에 도달하면 루프를 반복 재생하거나(데모 리허설용) 정지 안내 프레임을 표시한다 — 실제 데모 당일에는 항상 라이브 카메라 모드로 쓰므로 이 경로는 리허설 전용이다.

## 테스트

- `MonitoringPipeline` 옵저버 훅: 콜백이 프레임당 정확히 한 번 `(frame, tracking_batch, result)`로 호출되는지, 콜백을 넘기지 않을 때 기존 replay 결정론 테스트가 그대로 통과하는지 확인한다.
- `live_overlay_renderer`: 고정 프레임 배열 + 가짜 `TrackingBatch` + 가짜 `ZoneVisit`/`ParkingEpisode` 상태를 넣고, 반환된 JPEG를 디코드해 bbox 좌표의 픽셀 색이 기대한 상태색과 일치하는지 검증한다.
- `/live/stream` 엔드포인트: FastAPI `TestClient`로 `Content-Type`이 `multipart/x-mixed-replace`인지, 버퍼에 미리 넣은 JPEG가 그대로 응답 바디에 나오는지 확인한다.
- 리허설: 데모 전 `VideoFileFrameSource`로 파일럿 영상을 흘려보내 전체 경로(캡처→판정→렌더→스트리밍)를 카메라 없이 미리 검증한다.

## 한계

- 다수 동시 시청자나 원격(다른 네트워크) 시청은 범위 밖이다 — 단일 슬롯 버퍼 + MJPEG는 데모 부스 규모(같은 네트워크, 소수 시청자)에만 검증한다.
- 클라이언트 측 오버레이 토글, 녹화, 재생 컨트롤은 이번 범위에 없다.
- 젯슨 실기 성능(카메라 캡처+추론+인코딩+전송을 동시에 15fps로 유지할 수 있는지)은 리허설 단계에서 실측이 필요하다 — 코드 설계만으로는 보장할 수 없다.
