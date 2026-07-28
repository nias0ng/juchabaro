package com.ssafy.parking.common.response;
import com.ssafy.parking.common.exception.ErrorCode;

public record ApiResponse<T>(
        boolean success,
        String code,
        String message,
        T data
) {

    public static <T> ApiResponse<T> success(T data) {
        return new ApiResponse<>(
                true,
                "SUCCESS",
                "요청에 성공했습니다.",
                data
        );
    }

    public static ApiResponse<Void> successWithoutData() {
        return new ApiResponse<>(
                true,
                "SUCCESS",
                "요청에 성공했습니다.",
                null
        );
    }

    public static ApiResponse<Void> failure(ErrorCode errorCode) {
        return new ApiResponse<>(
                false,
                errorCode.name(),
                errorCode.getMessage(),
                null
        );
    }

    public static ApiResponse<Void> failure(
            ErrorCode errorCode,
            String message
    ) {
        return new ApiResponse<>(
                false,
                errorCode.name(),
                message,
                null
        );
    }
}