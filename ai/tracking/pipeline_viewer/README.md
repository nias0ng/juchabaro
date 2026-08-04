# Jetson Tracking Pipeline Viewer

입차 순간부터 시작하는 영상을 실제 Jetson tracking·session·parking workflow에
넣고, 정상 commit된 프레임별 관측과 상태 변화를 표시하는 Streamlit 도구입니다.

Viewer는 별도의 주차·Incident 판정을 구현하지 않습니다. 다음 운영 component를
직접 사용합니다.

- `EntryEventPayload`와 `EntryEventIntake`
- `VideoFileFrameSource`와 `RemapFrameSource`
- `UltralyticsVehicleTracker`
- `build_monitoring_pipeline()`
- `TrackingPipeline`과 `FrameObservationWorkflow`
- 실제 SQLite migration·repository·Unit of Work

Viewer 전용 대체 adapter는 임시 SQLite와 `JsonlPublicationPreparer`뿐입니다.
실제 카메라, Backend HTTP 전달·적용, GPIO actuator는 검증 범위가 아닙니다.

## 모델 배치

YOLO 가중치는 Git에 포함하지 않습니다. 기본 경로에 직접 배치합니다.

```text
hw/jetson/model/yolo26n.pt
```

## PC Conda 환경과 실행

Jetson 목표 환경과 같은 Python 3.10.12를 사용합니다. Viewer 의존성은
Jetson 운영 `requirements.txt`에 넣지 않고 PC 환경에 Streamlit만 추가합니다.

```powershell
conda create -n jetson-pipeline-viewer python=3.10.12 pip -y
conda activate jetson-pipeline-viewer

python -m pip install --upgrade pip setuptools wheel
python -m pip install -r hw/jetson/requirements.txt
python -m pip install streamlit
python -m pip check

streamlit run ai/tracking/pipeline_viewer/app.py
```

위 명령은 저장소 root에서 실행합니다. Jetson 장치에서는 JetPack과 호환되는
PyTorch·TensorRT 설치가 별도로 필요하므로 이 PC용 Conda 절차를 그대로 쓰지
않습니다.

## 입력 계약

- 영상 첫 프레임은 입차 순간입니다.
- `entryTime`은 `1970-01-01T00:00:00+00:00`이어야 합니다.
- 기본 synthetic ALLOW 예시는 현재 Jetson legacy wire 필드를 사용합니다.
- 이벤트는 DB에 직접 넣지 않고 실제 `EntryEventIntake.receive()`로 접수합니다.
- zone definition의 `calibrationReference`와 현재 calibration fingerprint가
  정확히 같아야 분석을 시작합니다.
- 모든 threshold와 tracker 설정은 화면에 표시하며 운영 component에 그대로
  전달합니다.

## 화면

- ALLOW 이벤트 JSON과 영상 업로드를 나란히 표시
- zone polygon, 차량 bbox, TrackSegment, motion, confidence overlay
- frame slider와 상태 변경 프레임 바로가기
- EntryMatch, ZoneVisit, ParkingEpisode, BlockingRelation, Incident 상태 변화
- 실제 `TrackingBatch`와 `FrameObservationResult` JSON 요약
- 기존 상태 변경 timeline의 명시적 CSV 다운로드
- 프레임별 YOLO detection·tracker 관측·차량 소실 진단 CSV 다운로드
- 정상 commit 이후의 프레임만 표시하고 오류 발생 시 마지막 정상 프레임과
  원래 예외를 함께 보존

진단 CSV의 `DETECTION` 행은 화면에서 설정한 YOLO confidence threshold를 통과한
post-NMS, pre-track 후보입니다. `TRACKED_VEHICLE` 행은 ByteTrack ID와
PhysicalVehicle ID가 부여되어 도메인으로 전달된 관측이며, detection이 없는
프레임도 `FRAME` 행으로 남습니다. 따라서 threshold보다 낮아 YOLO 결과에서
제거된 후보는 export에도 나타나지 않습니다. 낮은 confidence 분포를 확인하려면
Viewer 실행 전 threshold를 `0.01`처럼 낮추되, 후보 증가에 따른 오탐·처리시간
증가를 함께 비교해야 합니다. 현재 Viewer의 진단용 provisional 기본값은
`0.01`이며 운영 threshold를 뜻하지 않습니다.

실행 중 frame 이미지는 session별 임시 workspace에 JPEG로 저장됩니다. 새 실행을
시작하면 이전 workspace를 정리합니다.
