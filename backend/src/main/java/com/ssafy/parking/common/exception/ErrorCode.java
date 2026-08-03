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

    NOTIFICATION_QUERY_INVALID(
            HttpStatus.BAD_REQUEST,
            "알림 조회 조건이 올바르지 않습니다."
    ),

    NOTIFICATION_NOT_FOUND(
            HttpStatus.NOT_FOUND,
            "알림을 찾을 수 없습니다."
    ),

    NOTIFICATION_ACCESS_DENIED(
            HttpStatus.FORBIDDEN,
            "해당 알림에 접근할 권한이 없습니다."
    ),

    MOVE_REQUEST_NOT_FOUND(
            HttpStatus.NOT_FOUND,
            "이동 요청을 찾을 수 없습니다."
    ),

    MOVE_REQUEST_ACCESS_DENIED(
            HttpStatus.FORBIDDEN,
            "해당 이동 요청에 접근할 권한이 없습니다."
    ),

    MOVE_REQUEST_RESPONSE_INVALID(
            HttpStatus.BAD_REQUEST,
            "이동 요청 응답 값이 올바르지 않습니다."
    ),

    MOVE_REQUEST_RESPONSE_ACCESS_DENIED(
            HttpStatus.FORBIDDEN,
            "해당 이동 요청에 응답할 권한이 없습니다."
    ),

    MOVE_REQUEST_RESPONSE_NOT_ALLOWED(
            HttpStatus.CONFLICT,
            "현재 상태에서는 응답을 등록할 수 없습니다."
    ),

    USER_UPDATE_INVALID(
            HttpStatus.BAD_REQUEST,
            "회원 정보 수정 요청 값이 올바르지 않습니다."),

    CURRENT_PASSWORD_MISMATCH(
            HttpStatus.BAD_REQUEST,
            "현재 비밀번호가 일치하지 않습니다."),

    PARKING_SESSION_NOT_FOUND(
            HttpStatus.NOT_FOUND, "주차 세션을 찾을 수 없습니다."),

    HW_ZONE_NOT_FOUND(
            HttpStatus.NOT_FOUND, "해당 zoneId의 주차 구역을 찾을 수 없습니다."),

    HW_TRANSITION_INVALID(
            HttpStatus.UNPROCESSABLE_ENTITY, "지원하지 않는 전이 타입입니다."),

    HW_INCIDENT_NOT_FOUND(
            HttpStatus.NOT_FOUND, "해당 사건을 찾을 수 없습니다."),

    HW_INCIDENT_INVALID(
            HttpStatus.UNPROCESSABLE_ENTITY, "사건 전이 요청이 올바르지 않습니다."),

    HW_EVIDENCE_INVALID(
            HttpStatus.UNPROCESSABLE_ENTITY, "증거 이미지 요청이 올바르지 않습니다."),

    HW_EVIDENCE_TOO_LARGE(
            HttpStatus.PAYLOAD_TOO_LARGE, "증거 이미지 용량이 허용 범위를 초과했습니다."),

    INTERNAL_SERVER_ERROR(
            HttpStatus.INTERNAL_SERVER_ERROR,
            "서버 내부 오류가 발생했습니다."
    );

    private final HttpStatus httpStatus;
    private final String message;
}