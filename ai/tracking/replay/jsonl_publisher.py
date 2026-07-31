"""위반 이벤트를 JSONL 파일로 발행한다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TextIO

from jetson_vehicle_tracking_baseline import BaselineError, ViolationEvent, to_jsonable


class JsonlResultPublisher:
    """ViolationEvent를 한 줄에 하나씩 JSONL로 쓴다.

    직렬화는 baseline의 to_jsonable을 재사용한다 — StdoutResultPublisher와 규칙이
    갈라지면 검증 결과를 실제 발행 형식과 비교할 수 없게 된다.

    sort_keys로 키 순서를 고정하는 이유는 결정론이다. 같은 입력에 바이트로 같은
    출력이 나와야 파라미터를 바꿔가며 diff로 회귀 검사를 할 수 있다.
    """

    def __init__(self, *, path: Path) -> None:
        self._path = path
        self._handle: TextIO | None = None

    def __enter__(self) -> "JsonlResultPublisher":
        self.open()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def open(self) -> None:
        """출력 파일을 새로 만든다. 상위 디렉터리가 없으면 만든다."""

        if self._handle is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._path.open("w", encoding="utf-8", newline="\n")

    def publish(self, event: ViolationEvent) -> None:
        """이벤트 한 건을 JSON 한 줄로 쓴다."""

        if self._handle is None:
            raise BaselineError("JSONL 파일이 열려 있지 않습니다. open()을 먼저 호출하세요.")
        self._handle.write(
            json.dumps(to_jsonable(event), ensure_ascii=False, sort_keys=True) + "\n"
        )

    def close(self) -> None:
        """파일 핸들을 닫는다."""

        handle, self._handle = self._handle, None
        if handle is not None:
            handle.close()
