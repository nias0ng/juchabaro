"""Jetson 베이스라인의 내장 self-test를 팀 표준 pytest 실행에 편입한다.

리뷰 반영(I-7/319). jetson_vehicle_tracking_baseline.py는 unittest 모음을
파일 안에 들고 있고 `--self-test`로만 돌릴 수 있었다. 리포에 CI 설정이
없어서, 이 래퍼가 없으면 `pytest ai/training/tests`를 돌려도 위반 판정
로직의 회귀가 잡히지 않는다.

conftest.py가 ai/tracking을 sys.path에 넣으므로 그대로 import된다.
"""

from jetson_vehicle_tracking_baseline import run_self_tests


def test_tracking_self_tests_pass() -> None:
    assert run_self_tests() == 0
