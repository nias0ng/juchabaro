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

    INVALID_CREDENTIALS(
            HttpStatus.UNAUTHORIZED,
            "아이디 또는 비밀번호가 올바르지 않습니다."
    ),
    ACCOUNT_DISABLED(
            HttpStatus.FORBIDDEN,
            "사용할 수 없는 계정입니다."
    ),

    USER_NOT_FOUND(
            HttpStatus.NOT_FOUND,
            "사용자 정보를 찾을 수 없습니다."
    ),

    DUPLICATE_PLATE_NUMBER(
            HttpStatus.CONFLICT,
            "이미 등록된 차량 번호입니다."
    ),

    VEHICLE_NOT_FOUND(
            HttpStatus.NOT_FOUND,
            "차량 정보를 찾을 수 없습니다."
    ),

    VEHICLE_ACCESS_DENIED(
            HttpStatus.FORBIDDEN,
            "해당 차량에 접근할 권한이 없습니다."
    ),

    VEHICLE_UPDATE_INVALID(
            HttpStatus.BAD_REQUEST,
            "차량 수정 요청 값이 올바르지 않습니다."
    ),

    VEHICLE_UPDATE_ACCESS_DENIED(
            HttpStatus.FORBIDDEN,
            "해당 차량을 수정할 권한이 없습니다."
    ),

    VEHICLE_DELETE_ACCESS_DENIED(
            HttpStatus.FORBIDDEN,
            "해당 차량을 삭제할 권한이 없습니다."
    ),

    VEHICLE_HAS_ACTIVE_RECORD(
            HttpStatus.CONFLICT,
            "처리 중인 주차 기록이 있어 차량을 삭제할 수 없습니다."
    ),

    MOVE_REQUEST_INVALID(
            HttpStatus.BAD_REQUEST,
            "이동 요청 값이 올바르지 않습니다."
    ),

    MOVE_REQUEST_TARGET_NOT_FOUND(
            HttpStatus.NOT_FOUND,
            "이동 요청 대상 차량의 주차 정보를 찾을 수 없습니다."
    ),

    MOVE_REQUEST_ALREADY_EXISTS(
            HttpStatus.CONFLICT,
            "이미 처리 중인 이동 요청이 있습니다."
    ),

    MOVE_REQUEST_QUERY_INVALID(
            HttpStatus.BAD_REQUEST,
            "이동 요청 조회 조건이 올바르지 않습니다."
    ),

    INTERNAL_SERVER_ERROR(
            HttpStatus.INTERNAL_SERVER_ERROR,
            "서버 내부 오류가 발생했습니다."
    );

    private final HttpStatus httpStatus;
    private final String message;
}