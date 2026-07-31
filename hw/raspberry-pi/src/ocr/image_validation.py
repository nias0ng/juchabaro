"""OCR 경계에서 재사용하는 BGR 이미지 형식 판별."""

from __future__ import annotations

from typing import TypeGuard

import numpy as np

from .types import BgrImage


def is_nonempty_bgr_uint8_image(
    value: object,
) -> TypeGuard[BgrImage]:
    """값이 비어 있지 않은 BGR uint8 HxWx3 배열인지 판별한다."""

    return (
        isinstance(value, np.ndarray)
        and value.dtype == np.uint8
        and value.ndim == 3
        and value.shape[2] == 3
        and value.shape[0] > 0
        and value.shape[1] > 0
    )
