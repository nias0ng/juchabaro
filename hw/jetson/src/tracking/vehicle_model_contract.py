"""차량 검출 모델이 모든 실행 표면에서 공유하는 runtime 의미 계약.

운영 release의 binary 식별과 SHA 검증은 ``model_manifest``가 담당한다.
이 모듈은 배포 방식과 무관하게 tracker가 요구하는 task와 class map만 정의한다.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


VEHICLE_MODEL_TASK = "detect"
VEHICLE_MODEL_CLASS_NAMES: Mapping[int, str] = MappingProxyType({0: "vehicle"})
