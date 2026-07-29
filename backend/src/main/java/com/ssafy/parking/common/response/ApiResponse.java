package com.ssafy.parking.common.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.ssafy.parking.common.exception.ErrorCode;
import org.springframework.http.HttpStatus;

public record ApiResponse<T>(
        String httpStatus,
        @JsonProperty("isSuccess") boolean isSuccess,
        String message,
        int code,
        T result
) {

    public static <T> ApiResponse<T> success(HttpStatus status, String message, T result) {
        return new ApiResponse<>(status.name(), true, message, status.value(), result);
    }

    public static <T> ApiResponse<T> success(T result) {
        return success(HttpStatus.OK, "요청에 성공했습니다.", result);
    }

    public static ApiResponse<Void> successWithoutData() {
        return new ApiResponse<>(
                HttpStatus.OK.name(),
                true,
                "요청에 성공했습니다.",
                HttpStatus.OK.value(),
                null
        );
    }

    public static ApiResponse<Void> failure(ErrorCode errorCode) {
        HttpStatus status = errorCode.getHttpStatus();
        return new ApiResponse<>(
                status.name(),
                false,
                errorCode.getMessage(),
                status.value(),
                null
        );
    }

    public static ApiResponse<Void> failure(ErrorCode errorCode, String message) {
        HttpStatus status = errorCode.getHttpStatus();
        return new ApiResponse<>(
                status.name(),
                false,
                message,
                status.value(),
                null
        );
    }
}