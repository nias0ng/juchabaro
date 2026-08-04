"""Jetson HTTP 오류를 Backend ``ApiResponse`` envelope로 직렬화한다.

라우터는 도메인 오류를 적절한 HTTP status로 변환하는 책임만 가진다. 이 모듈은
FastAPI의 HTTP·request validation·예기치 않은 오류를 공통 wire 형식으로 바꾸며,
내부 예외 상세나 stack trace는 응답에 노출하지 않는다.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger(__name__)

_BACKEND_HTTP_STATUS_NAMES = {
    # Python 3.14부터 422의 canonical name이 UNPROCESSABLE_CONTENT로 바뀌었지만,
    # Backend Spring HttpStatus 계약은 UNPROCESSABLE_ENTITY를 사용한다.
    HTTPStatus.UNPROCESSABLE_ENTITY: "UNPROCESSABLE_ENTITY",
}
_DEFAULT_ERROR_METADATA = {
    HTTPStatus.BAD_REQUEST: ("INVALID_REQUEST", False),
    HTTPStatus.UNAUTHORIZED: ("INTERNAL_API_KEY_INVALID", False),
    HTTPStatus.NOT_FOUND: ("TARGET_NOT_FOUND", False),
    HTTPStatus.CONFLICT: ("STATE_CONFLICT", False),
    HTTPStatus.UNPROCESSABLE_ENTITY: ("INVALID_REQUEST", False),
    HTTPStatus.SERVICE_UNAVAILABLE: (
        "DURABLE_STORAGE_UNAVAILABLE",
        True,
    ),
    HTTPStatus.INTERNAL_SERVER_ERROR: ("INTERNAL_SERVER_ERROR", True),
}


class JetsonApiError(StarletteHTTPException):
    """기계 판독 가능한 error type과 retry 성격을 가진 API 오류."""

    def __init__(
        self,
        *,
        status_code: int,
        error_type: str,
        message: str,
        retryable: bool = False,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.error_type = error_type
        self.retryable = retryable


def failure_envelope(
    *,
    status_code: int,
    message: str,
    error_type: str,
    retryable: bool,
) -> dict[str, object]:
    """Backend ``ApiResponse.failure``와 같은 JSON object를 만든다."""

    try:
        status = HTTPStatus(status_code)
        http_status = _BACKEND_HTTP_STATUS_NAMES.get(status, status.name)
    except ValueError:
        http_status = str(status_code)
    return {
        "httpStatus": http_status,
        "isSuccess": False,
        "message": message,
        "code": status_code,
        "result": {
            "errorType": error_type,
            "retryable": retryable,
        },
    }


def register_error_handlers(application: FastAPI) -> None:
    """application 전체에 공통 실패 응답 계약을 등록한다."""

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _request: Request,
        error: StarletteHTTPException,
    ) -> JSONResponse:
        error_type, retryable = _error_metadata(error)
        return JSONResponse(
            status_code=error.status_code,
            content=failure_envelope(
                status_code=error.status_code,
                message=_detail_message(error.detail),
                error_type=error_type,
                retryable=retryable,
            ),
            headers=error.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        _request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            content=failure_envelope(
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                message=_validation_message(error),
                error_type="INVALID_REQUEST",
                retryable=False,
            ),
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request,
        error: Exception,
    ) -> JSONResponse:
        logger.error(
            "처리되지 않은 Jetson API 예외: %s %s",
            request.method,
            request.url.path,
            exc_info=(type(error), error, error.__traceback__),
        )
        return JSONResponse(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            content=failure_envelope(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                message="내부 서버 오류가 발생했습니다.",
                error_type="INTERNAL_SERVER_ERROR",
                retryable=True,
            ),
        )


def _detail_message(detail: Any) -> str:
    if isinstance(detail, str) and detail:
        return detail
    return "요청 처리에 실패했습니다."


def _validation_message(error: RequestValidationError) -> str:
    errors = error.errors()
    if not errors:
        return "요청 값이 올바르지 않습니다."
    first = errors[0]
    message = first.get("msg")
    if not isinstance(message, str) or not message:
        return "요청 값이 올바르지 않습니다."
    location = ".".join(str(part) for part in first.get("loc", ()))
    return f"{location}: {message}" if location else message


def _error_metadata(error: StarletteHTTPException) -> tuple[str, bool]:
    if isinstance(error, JetsonApiError):
        return error.error_type, error.retryable
    try:
        status = HTTPStatus(error.status_code)
    except ValueError:
        return "HTTP_ERROR", False
    return _DEFAULT_ERROR_METADATA.get(status, ("HTTP_ERROR", False))
