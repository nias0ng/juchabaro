import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
# ai/tracking의 Jetson 베이스라인·캘리브레이션 모듈도 테스트 대상이다. 베이스라인 스크립트가
# `import calibration_utils`(모듈명 그대로)를 하므로 이 경로가 sys.path에 있어야 한다.
sys.path.insert(0, str(ROOT.parent / "tracking"))
