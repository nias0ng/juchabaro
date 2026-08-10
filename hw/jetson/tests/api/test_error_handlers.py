"""Backend ApiResponse와 동일한 Jetson 실패 envelope 계약 테스트."""

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from src.api.error_handlers import register_error_handlers


class RequiredPayload(BaseModel):
    value: int


def _client() -> TestClient:
    application = FastAPI()
    register_error_handlers(application)

    @application.get("/conflict")
    def conflict() -> None:
        raise HTTPException(status_code=409, detail="revision이 충돌합니다.")

    @application.post("/validation")
    def validation(_payload: RequiredPayload) -> None:
        return None

    @application.get("/unexpected")
    def unexpected() -> None:
        raise RuntimeError("응답에 노출하면 안 되는 상세")

    return TestClient(application, raise_server_exceptions=False)


def test_http_exception_uses_backend_failure_envelope() -> None:
    response = _client().get("/conflict")

    assert response.status_code == 409
    assert response.json() == {
        "httpStatus": "CONFLICT",
        "isSuccess": False,
        "message": "revision이 충돌합니다.",
        "code": 409,
        "result": {
            "errorType": "STATE_CONFLICT",
            "retryable": False,
        },
    }


def test_request_validation_uses_backend_failure_envelope() -> None:
    response = _client().post("/validation", json={})

    assert response.status_code == 422
    assert response.json()["httpStatus"] == "UNPROCESSABLE_ENTITY"
    assert response.json()["isSuccess"] is False
    assert response.json()["code"] == 422
    assert response.json()["result"] == {
        "errorType": "INVALID_REQUEST",
        "retryable": False,
    }
    assert "value" in response.json()["message"]


def test_unexpected_error_hides_internal_detail() -> None:
    response = _client().get("/unexpected")

    assert response.status_code == 500
    assert response.json() == {
        "httpStatus": "INTERNAL_SERVER_ERROR",
        "isSuccess": False,
        "message": "내부 서버 오류가 발생했습니다.",
        "code": 500,
        "result": {
            "errorType": "INTERNAL_SERVER_ERROR",
            "retryable": True,
        },
    }
