#!/usr/bin/env python3
"""실제 USB speaker에서 경고음 adapter의 projection 흐름을 수동 확인한다.

기존 ``JetsonUsbSpeakerAdapter``와 ``AplayAudioBackend``의 공개 API만 사용해
단독 반복, OFF 중단과 cursor 초기화, 고정 round-robin 순서를 확인한다. ALSA,
mixer, 음량이나 실제 음향 결과는 자동 검증하지 않는다.

실행 예::

    cd hw/jetson
    python -m scripts.check_warning_speaker \
        --device "plughw:CARD=Device,DEV=0" \
        --disabled-wav /home/e202/assets/audio/disabled_zone_warning.wav \
        --ev-wav /home/e202/assets/audio/ev_zone_warning.wav

CLI 시간 기본값은 약 4초 WAV를 듣기 위한 provisional 수동 진단값이며 운영
재생 정책이 아니다.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from src.actuators.adapters.audio_backend import AplayAudioBackend
from src.actuators.adapters.jetson_usb_speaker import (
    DISABLED_ZONE_WARNING_SPEAKER_ID,
    EV_ZONE_WARNING_SPEAKER_ID,
    PLAY_ACTION,
    JetsonUsbSpeakerAdapter,
)
from src.actuators.models import ActuatorCommand


DEFAULT_DEVICE = "plughw:CARD=Device,DEV=0"
DEFAULT_DISABLED_WAV_PATH = Path(
    "/home/e202/assets/audio/disabled_zone_warning.wav"
)
DEFAULT_EV_WAV_PATH = Path(
    "/home/e202/assets/audio/ev_zone_warning.wav"
)
DEFAULT_SINGLE_STAGE_SECONDS = 5.0
DEFAULT_ROUND_ROBIN_STAGE_SECONDS = 10.0
DEFAULT_OFF_SECONDS = 1.0
DIAGNOSTIC_REASON = "MANUAL_HARDWARE_DIAGNOSTIC"


class WarningSpeakerDiagnosticAdapter(Protocol):
    """진단 스크립트가 사용하는 경고 speaker adapter 최소 계약."""

    @property
    def failure(self) -> Exception | None:
        """최초 startup 또는 background terminal 오류."""

    def open(self) -> None:
        """WAV, backend와 worker를 초기화한다."""

    def apply_projection(
        self,
        commands: tuple[ActuatorCommand, ...],
    ) -> None:
        """전체 현재 speaker projection을 적용한다."""

    def close(self) -> None:
        """현재 재생을 중단하고 worker와 backend를 정리한다."""


class _BackgroundFailureDetected(RuntimeError):
    """Background worker의 terminal 오류가 확인된 진단 실패."""

    def __init__(self, failure: Exception) -> None:
        super().__init__(
            "USB 경고 speaker background worker가 실패했습니다: "
            f"{failure}"
        )
        self.failure = failure
        self.__cause__ = failure


def _non_blank_string(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise argparse.ArgumentTypeError(
            "비어 있지 않은 문자열이어야 합니다."
        )
    return normalized


def _positive_finite_float(value: str) -> float:
    try:
        parsed_value = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "유한한 양수여야 합니다."
        ) from error

    if not math.isfinite(parsed_value) or parsed_value <= 0:
        raise argparse.ArgumentTypeError("유한한 양수여야 합니다.")
    return parsed_value


def _non_negative_finite_float(value: str) -> float:
    try:
        parsed_value = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "유한한 0 이상의 숫자여야 합니다."
        ) from error

    if not math.isfinite(parsed_value) or parsed_value < 0:
        raise argparse.ArgumentTypeError(
            "유한한 0 이상의 숫자여야 합니다."
        )
    return parsed_value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--device",
        type=_non_blank_string,
        default=DEFAULT_DEVICE,
        help="ALSA PCM 장치. 기본값: %(default)s",
    )
    parser.add_argument(
        "--disabled-wav",
        type=Path,
        default=DEFAULT_DISABLED_WAV_PATH,
        help="장애인 구역 경고 WAV 경로. 기본값: %(default)s",
    )
    parser.add_argument(
        "--ev-wav",
        type=Path,
        default=DEFAULT_EV_WAV_PATH,
        help="전기차 구역 경고 WAV 경로. 기본값: %(default)s",
    )
    parser.add_argument(
        "--single-stage-seconds",
        type=_positive_finite_float,
        default=DEFAULT_SINGLE_STAGE_SECONDS,
        help=(
            "각 단독 반복을 듣는 시간(초). 기본값 %(default)s는 "
            "provisional 수동 진단값입니다."
        ),
    )
    parser.add_argument(
        "--round-robin-stage-seconds",
        type=_positive_finite_float,
        default=DEFAULT_ROUND_ROBIN_STAGE_SECONDS,
        help=(
            "round-robin을 듣는 시간(초). 기본값 %(default)s는 "
            "provisional 수동 진단값입니다."
        ),
    )
    parser.add_argument(
        "--off-seconds",
        type=_non_negative_finite_float,
        default=DEFAULT_OFF_SECONDS,
        help=(
            "OFF 상태를 확인하는 시간(초). 기본값 %(default)s는 "
            "provisional 수동 진단값입니다."
        ),
    )
    return parser


def build_adapter(
    *,
    device: str,
    disabled_wav_path: Path,
    ev_wav_path: Path,
) -> WarningSpeakerDiagnosticAdapter:
    """기존 production backend와 adapter를 수동 진단 설정으로 조립한다."""

    backend = AplayAudioBackend(device=device)
    return JetsonUsbSpeakerAdapter(
        backend=backend,
        disabled_zone_warning_wav_path=disabled_wav_path,
        ev_zone_warning_wav_path=ev_wav_path,
    )


def _command(actuator_id: str) -> ActuatorCommand:
    return ActuatorCommand(
        actuator_id=actuator_id,
        action=PLAY_ACTION,
        reason=DIAGNOSTIC_REASON,
        requested_at=datetime.now(timezone.utc),
    )


def _raise_if_background_failed(
    adapter: WarningSpeakerDiagnosticAdapter,
) -> None:
    failure = adapter.failure
    if failure is not None:
        raise _BackgroundFailureDetected(failure)


def _sleep_if_positive(
    seconds: float,
    *,
    sleep: Callable[[float], None],
) -> None:
    if seconds > 0:
        sleep(seconds)


def run(
    *,
    adapter: WarningSpeakerDiagnosticAdapter,
    single_stage_seconds: float,
    round_robin_stage_seconds: float,
    off_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """수동 진단 projection을 실행하고 background 오류와 cleanup을 확인한다."""

    exit_code = 0
    phase = "초기화"
    reported_errors: list[BaseException] = []

    def was_reported(error: BaseException) -> bool:
        return any(
            error is reported_error
            for reported_error in reported_errors
        )

    def report_once(error: BaseException, message: str) -> None:
        if was_reported(error):
            return
        reported_errors.append(error)
        print(message, file=sys.stderr)

    try:
        adapter.open()
        print("USB 경고 speaker adapter 초기화 성공")

        phase = "장애인 구역 경고음 단독 반복"
        print("[1/3] 장애인 구역 경고음 단독 반복을 확인하세요.")
        adapter.apply_projection(
            (_command(DISABLED_ZONE_WARNING_SPEAKER_ID),)
        )
        sleep(single_stage_seconds)
        _raise_if_background_failed(adapter)

        phase = "첫 번째 OFF"
        print("[OFF] 현재 음성이 즉시 중단되는지 확인하세요.")
        adapter.apply_projection(())
        _sleep_if_positive(off_seconds, sleep=sleep)
        _raise_if_background_failed(adapter)

        phase = "전기차 구역 경고음 단독 반복"
        print("[2/3] 전기차 구역 경고음 단독 반복을 확인하세요.")
        adapter.apply_projection(
            (_command(EV_ZONE_WARNING_SPEAKER_ID),)
        )
        sleep(single_stage_seconds)
        _raise_if_background_failed(adapter)

        phase = "두 번째 OFF"
        print("[OFF] 현재 음성이 즉시 중단되는지 확인하세요.")
        adapter.apply_projection(())
        _sleep_if_positive(off_seconds, sleep=sleep)
        _raise_if_background_failed(adapter)

        phase = "고정 round-robin"
        print(
            "[3/3] disabled → ev 순서로 연속 교대하는지 확인하세요."
        )
        adapter.apply_projection(
            (
                _command(EV_ZONE_WARNING_SPEAKER_ID),
                _command(DISABLED_ZONE_WARNING_SPEAKER_ID),
            )
        )
        sleep(round_robin_stage_seconds)
        _raise_if_background_failed(adapter)

        phase = "최종 OFF"
        print("[OFF] 최종 음성 중단을 확인하세요.")
        adapter.apply_projection(())
        _sleep_if_positive(off_seconds, sleep=sleep)
        _raise_if_background_failed(adapter)
    except KeyboardInterrupt as error:
        report_once(
            error,
            "USB 경고 speaker 진단이 사용자에 의해 중단되었습니다.",
        )
        exit_code = 1
    except _BackgroundFailureDetected as error:
        report_once(error.failure, str(error))
        exit_code = 1
    except Exception as error:
        report_once(
            error,
            f"USB 경고 speaker 진단 {phase}에 실패했습니다: {error}",
        )
        exit_code = 1
    finally:
        try:
            adapter.close()
        except KeyboardInterrupt as error:
            report_once(
                error,
                "USB 경고 speaker cleanup이 사용자에 의해 "
                "중단되었습니다.",
            )
            exit_code = 1
        except Exception as error:
            report_once(
                error,
                f"USB 경고 speaker cleanup에 실패했습니다: {error}",
            )
            exit_code = 1

        try:
            final_failure = adapter.failure
        except Exception as error:
            report_once(
                error,
                "USB 경고 speaker background failure 상태를 확인할 수 "
                f"없습니다: {error}",
            )
            exit_code = 1
        else:
            if final_failure is not None:
                already_reported = was_reported(final_failure)
                report_once(
                    final_failure,
                    "USB 경고 speaker background worker가 실패했습니다: "
                    f"{final_failure}",
                )
                if not already_reported:
                    exit_code = 1

    if exit_code == 0:
        print("USB 경고 speaker 진단 실행과 cleanup을 완료했습니다.")
        print("음성 종류·순서·음량은 사용자가 직접 확인해야 합니다.")

    return exit_code


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        adapter = build_adapter(
            device=args.device,
            disabled_wav_path=args.disabled_wav,
            ev_wav_path=args.ev_wav,
        )
    except KeyboardInterrupt:
        print(
            "USB 경고 speaker 진단 준비가 사용자에 의해 중단되었습니다.",
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        print(
            "USB 경고 speaker 진단 adapter를 준비할 수 없습니다: "
            f"{error}",
            file=sys.stderr,
        )
        return 1

    return run(
        adapter=adapter,
        single_stage_seconds=args.single_stage_seconds,
        round_robin_stage_seconds=args.round_robin_stage_seconds,
        off_seconds=args.off_seconds,
    )


if __name__ == "__main__":
    sys.exit(main())
