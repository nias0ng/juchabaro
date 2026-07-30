# OCR Pipeline Viewer

`hw/raspberry-pi/src/ocr`의 운영 파이프라인을 PC에서 그대로 실행하고,
현재 viewer 기본 profile인 6프레임 처리의 단계별 입출력을 Streamlit으로
관찰하는 도구입니다. 운영 OCR pipeline 자체는 공유 정책에 따라 다른
프레임 수도 지원하지만, 이 viewer의 업로드 UI와 기본 runtime은 6프레임
profile로 조립됩니다.

이 디렉터리는 모델 학습이나 모델 파일 다운로드를 담당하지 않습니다.
모델과 이를 공유하는 runtime component·실행 lock을 Streamlit 프로세스에서
캐시하며, 각 사용자 실행의 trace는 해당 Streamlit session에만 보관합니다.

## 모델 배치

저장소의 다음 위치에 모델을 배치합니다.

```text
hw/raspberry-pi/models/
├── plate_detector/
│   └── bestv1_1.pt
└── plate_recognizer/
    ├── inference.json
    ├── inference.pdiparams
    └── inference.yml
```

Raspberry Pi 배포 시에는 같은 하위 구조가 `/home/e202/models`로
이동한다는 현재 배포 계약을 전제로 합니다.

모델 파일은 Git에서 제외되며 이 앱은 파일을 생성하거나 다운로드하지
않습니다.

## Python 3.13 환경

새 PC 환경을 만드는 예시는 다음과 같습니다.

```powershell
conda create -n plate-ocr-viewer python=3.13 pip -y
conda activate plate-ocr-viewer

python -m pip install --upgrade pip setuptools wheel
python -m pip install paddlepaddle==3.3.1 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
python -m pip install paddleocr==3.7.0 "paddlex[ocr-core]==3.7.2" ultralytics==8.4.108 streamlit pillow
python -m pip check
```

이미 OCR 파이프라인 의존성이 설치된 환경이라면 Viewer 추가 의존성만
설치합니다.

```powershell
python -m pip install --upgrade streamlit pillow
```

`Pillow`는 업로드 이미지의 EXIF 방향을 적용하는 데 사용합니다.
Streamlit과 함께 설치되는 경우가 많지만 이 앱에서 직접 import하므로
명시했습니다.

## 실행

저장소 루트에서 실행합니다.

```powershell
streamlit run ai/ocr/pipeline_viewer/app.py
```

앱의 첫 실행은 다음 작업을 한 번 수행합니다.

1. YOLO 모델 로드
2. YOLO 검은 이미지 dummy inference
3. PaddleOCR recognition 모델 로드
4. PaddleOCR 검은 번호판 이미지 dummy inference

모델 준비 결과는 `st.cache_resource`에 보관되므로 일반 UI rerun에서는
반복하지 않습니다. 모델 파일을 교체한 경우 사이드바의
`모델 다시 로드` 버튼으로 명시적으로 갱신합니다.

## 현재 viewer 기본 profile의 입력 계약

- 사진은 정확히 6장이어야 합니다.
- 파일명을 자연 정렬한 순서가 실제 촬영 시간순이어야 합니다.
- 모든 사진의 해상도가 같아야 합니다.
- 앱은 EXIF 방향을 적용한 뒤 BGR `uint8 HxWx3` 이미지로 변환합니다.
- 권장 파일명은 `01.jpg`부터 `06.jpg`까지입니다.

## 화면

- 최종 판정, trace에서 복원한 후보와 단계 실패
- 품질 비교로 선택된 앞쪽 anchor와 마지막 anchor
- Anchor별 YOLO 후보 전체의 best-first 순위·bbox·confidence와 best 후보의
  네 keypoint overlay
- 프레임별 검출·보간·외삽·재사용 quad
- 원근 보정 및 OCR 전처리 전후 이미지
- PaddleOCR 원문, confidence, 정규화 문자열과 형식 검사
- 최종 투표 결과
- trace 기반 단계별 함수 실행 시간과 실제 함수별 입출력 요약

운영용 `PlateReadResult`에는 상태와 성공 번호판만 남긴다. 후보, 투표 상세,
단계별 오류와 timing은 viewer의 실행별 `PipelineTrace`에서만 읽는다.
Pipeline 실행이 예외로 끝나도 완료 전까지 기록된 component 호출과 전체
실행 오류를 같은 trace에서 확인할 수 있다. Adapter가 감싼 예외도
root부터 원인까지 type과 message chain을 보존한다.

이미지는 원본 배열을 수정하지 않은 복사본에만 overlay합니다. 원시
입출력 JSON에서는 NumPy 배열을 복사하지 않고 shape와 dtype만 보여줍니다.
Detector trace는 anchor 호출마다 한 번만 기록하며, 출력은 best-first
`DetectedPlate` tuple입니다. 빈 tuple은 정상 미검출입니다. 화면에서는
best 후보를 overlay하고 전체 후보를 best-first 표로 보여줍니다. Trace는
같은 프로세스에서 운영 component가 만든 typed output을 그대로 사용하며,
이미지를 표시할 때만 BGR 배열 계약을 확인합니다.
