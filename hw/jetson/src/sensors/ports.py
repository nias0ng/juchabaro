"""상위 코드와 외부 센서 하드웨어 어댑터 사이의 입력 Port.

이 모듈은 센서 배열의 초기화, 측정, 정리 계약과 생명주기 오류만 소유한다.
센서별 측정 구현, 측정값 해석 또는 전체 센서·액추에이터 파이프라인은
소유하지 않는다.

이 Port는 thread-safe를 보장하지 않는다. 하나의 owner가 ``open()``,
``read_all()``, ``close()``를 직렬로 호출해야 하며, 측정 중 다른 thread에서
``close()``를 호출해서는 안 된다. 동기화는 후속 polling worker의 책임이다.
"""

from __future__ import annotations

from typing import Protocol

from src.sensors.models import SensorReadBatch


class SensorArrayError(RuntimeError):
    """센서 배열 생명주기에서 발생한 공통 오류."""


class SensorArrayInitializationError(SensorArrayError):
    """센서 배열 초기화가 완료되지 못한 오류."""


class SensorArrayStateError(SensorArrayError):
    """현재 생명주기 상태에서 허용되지 않는 작업 오류."""


class SensorArrayCleanupError(SensorArrayError):
    """자원 정리를 모두 시도했지만 하나 이상 실패한 오류."""


class SensorArray(Protocol):
    """센서 배열의 초기화, 일괄 측정, 정리 생명주기 계약."""

    def open(self) -> None:
        """구성된 모든 센서를 초기화하고 측정 가능한 상태로 만든다.

        반복 호출이 안전한 멱등 동작이어야 한다. 초기화에 실패하면 부분적으로
        획득한 자원을 정리하고 ``SensorArrayInitializationError``를 발생시킨다.
        실패한 뒤 다시 호출해 초기화를 시도할 수 있어야 한다.
        """

    def read_all(self) -> SensorReadBatch:
        """구성된 센서를 설정 순서대로 각각 한 번 읽은 결과를 반환한다.

        각 센서는 성공 또는 실패 중 하나의 결과를 생성한다. 한 센서가 실패해도
        나머지 센서 측정을 계속하며, 모든 센서가 실패한 경우에도 실패가 담긴
        ``SensorReadBatch``를 반환한다.

        ``open()`` 전에 호출하면 ``SensorArrayStateError``를 발생시킨다.
        거리값을 점유 상태나 주차 상태로 해석하지 않으며, 정확히 센서 두 개가
        구성되어 있다는 조건을 보장하지 않는다.
        """

    def close(self) -> None:
        """센서 배열이 획득한 모든 자원의 정리를 시도한다.

        부분 초기화 상태나 열지 않은 상태에서도 호출할 수 있고, 반복 호출이
        안전한 멱등 동작이어야 한다. 일부 자원 정리에 실패해도 나머지 정리를
        계속하며, 실패가 남으면 모든 정리 시도 후
        ``SensorArrayCleanupError``를 발생시킨다.
        """
