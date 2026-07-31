"""관측 시각(`observed_at`)에 대한 공통 사전조건 검사.

`zone_visit_tracker`와 `incident_reducer`는 둘 다 프레임 순서에 의존하는 상태를
들고 있고, 둘 다 같은 두 가지 잘못된 입력에 똑같이 취약하다. 검사를 두 모듈에
복사해 두면 한쪽만 고쳐지므로 여기 하나만 둔다.

- naive datetime: 타임존이 다른 관측이 섞이면 간격 계산이 조용히 틀린다.
- 과거로 되돌아간 관측: 프레임이 뒤섞이면 방문 트래커의 누적 시간이 음수가 되어
  (실측 -5.0초) 진입 확정이 조용히 늦어지고, 사건 축약기는 `confirmed_at`보다
  앞선 `resolved_at`을 만들어 위반 지속시간이 음수인 채로 백엔드에 나간다.

되돌아간 관측은 **무시하지 않고 예외를 던진다.** 조용히 넘기면 프레임을 재정렬한
실행과 정상 실행의 판정 결과가 달라지는데, 리플레이 검증은 바로 그 차이가 없음을
확인하려고 존재한다. 프레임을 뒤섞는 도구는 여기서 시끄럽게 실패해야 한다. 같은
시각(`==`)은 허용한다 — 한 프레임 안의 여러 관측은 같은 `observed_at`을 공유하고,
확인시간이 0인 설정에서는 같은 시각의 연속 갱신이 정상 경로다.
"""

from __future__ import annotations

from datetime import datetime


def ensure_forward_observation(
    observed_at: datetime, previous: datetime | None = None
) -> None:
    """`observed_at`이 timezone-aware이고 직전 관측보다 뒤인지 검사한다.

    `previous`가 `None`이면(해당 상태의 첫 관측) 순서 검사를 건너뛴다.
    """

    if observed_at.tzinfo is None:
        raise ValueError("observed_at은 timezone-aware datetime이어야 합니다.")
    if previous is not None and observed_at < previous:
        raise ValueError(
            "observed_at이 직전 관측보다 과거입니다: "
            f"{observed_at.isoformat()} < {previous.isoformat()}"
        )
