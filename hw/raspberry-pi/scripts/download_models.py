'''
models에 모델 파일이 없을 때 실행
번호판 탐지 모델: YOLOv8n-pose (파인튜닝)
번호판 OCR 모델: paddleOCR (최신버전)
'''

'''
models 폴더 생성
하위 폴더
- plate_detector : YOLOv8n-pose
- plate_recognizer : paddleOCR
'''

from pathlib import Path

BASE_DIR = Path("/home/e202/")
MODELS_DIR = BASE_DIR / "models"

PLATE_DETECTOR_DIR = MODELS_DIR / "plate_detector"
PLATE_RECOGNIZER_DIR = MODELS_DIR / "plate_recognizer"

PLATE_DETECTOR_DIR.mkdir(parents=True, exist_ok=True)
PLATE_RECOGNIZER_DIR.mkdir(parents=True, exist_ok=True)

PLATE_DETECTOR_MODEL_PATH = PLATE_DETECTOR_DIR / "best.pt"  # 대충 임시로 아무 모델 이름 해놨음 모델 로드 코드 만들고 바꿀 것
PLATE_RECOGNIZER_MODEL_DIR = PLATE_RECOGNIZER_DIR  # 얘는 폴더에 통짜로 생성