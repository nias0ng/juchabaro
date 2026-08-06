package com.ssafy.parking.common.exception;

import com.ssafy.parking.common.response.ApiResponse;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import static org.assertj.core.api.Assertions.assertThat;

class GlobalExceptionHandlerTest {

    private final GlobalExceptionHandler handler =
            new GlobalExceptionHandler();

    @Test
    void handleBusinessException() {
        BusinessException exception =
                new BusinessException(ErrorCode.RESOURCE_NOT_FOUND);

        ResponseEntity<ApiResponse<Void>> response =
                handler.handleBusinessException(exception);

        assertThat(response.getStatusCode())
                .isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().isSuccess()).isFalse();
        assertThat(response.getBody().httpStatus())
                .isEqualTo("NOT_FOUND");
        assertThat(response.getBody().code()).isEqualTo(404);
    }

    @Test
    void idempotencyInProgressIsRetryableButPayloadConflictRemainsTerminal() {
        ResponseEntity<ApiResponse<Void>> inProgress =
                handler.handleBusinessException(
                        new BusinessException(
                                ErrorCode.HW_IDEMPOTENCY_IN_PROGRESS
                        )
                );

        assertThat(inProgress.getStatusCode())
                .isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
        assertThat(inProgress.getBody()).isNotNull();
        assertThat(inProgress.getBody().isSuccess()).isFalse();
        assertThat(inProgress.getBody().httpStatus())
                .isEqualTo("SERVICE_UNAVAILABLE");
        assertThat(inProgress.getBody().code()).isEqualTo(503);

        ResponseEntity<ApiResponse<Void>> conflict =
                handler.handleBusinessException(
                        new BusinessException(
                                ErrorCode.HW_IDEMPOTENCY_CONFLICT
                        )
                );

        assertThat(conflict.getStatusCode())
                .isEqualTo(HttpStatus.CONFLICT);
        assertThat(conflict.getBody()).isNotNull();
        assertThat(conflict.getBody().httpStatus())
                .isEqualTo("CONFLICT");
        assertThat(conflict.getBody().code()).isEqualTo(409);
    }

    @Test
    void handleUnreadableMessage() {
        ResponseEntity<ApiResponse<Void>> response =
                handler.handleUnreadableMessage();

        assertThat(response.getStatusCode())
                .isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().message())
                .isEqualTo("요청 본문의 형식이 올바르지 않습니다.");
    }

    @Test
    void handleUnexpectedException() {
        ResponseEntity<ApiResponse<Void>> response =
                handler.handleUnexpectedException(
                        new RuntimeException("test exception")
                );

        assertThat(response.getStatusCode())
                .isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().httpStatus())
                .isEqualTo("INTERNAL_SERVER_ERROR");
        assertThat(response.getBody().code()).isEqualTo(500);
    }
}
