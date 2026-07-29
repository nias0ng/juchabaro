package com.ssafy.parking.common.exception;

import lombok.Getter;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;

@Getter
@RequiredArgsConstructor
public enum ErrorCode {

    INVALID_INPUT_VALUE(
            HttpStatus.BAD_REQUEST,
            "입력값이 올바르지 않습니다."
    ),

    RESOURCE_NOT_FOUND(
            HttpStatus.NOT_FOUND,
            "요청한 리소스를 찾을 수 없습니다."
    ),

    DUPLICATE_LOGIN_ID(
            HttpStatus.CONFLICT,
            "이미 사용 중인 로그인 아이디입니다."
    ),

    INTERNAL_SERVER_ERROR(
            HttpStatus.INTERNAL_SERVER_ERROR,
            "서버 내부 오류가 발생했습니다."
    );

    private final HttpStatus httpStatus;
    private final String message;
}