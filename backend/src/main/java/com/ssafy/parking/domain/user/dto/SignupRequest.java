package com.ssafy.parking.domain.user.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;

public record SignupRequest(
        @Schema(description = "로그인 아이디", example = "chaewon01")
        @NotBlank(message = "회원가입 요청 값이 올바르지 않습니다.") String loginId,

        @Schema(description = "비밀번호", example = "Password123!")
        @NotBlank(message = "회원가입 요청 값이 올바르지 않습니다.") String password,

        @Schema(description = "전화번호(하이픈 제외)", example = "01012345678")
        @NotBlank(message = "회원가입 요청 값이 올바르지 않습니다.") String phoneNumber,

        @Schema(description = "이름", example = "김싸피")
        @NotBlank(message = "회원가입 요청 값이 올바르지 않습니다.") String name,

        @Schema(description = "아파트 동", example = "101")
        @NotBlank(message = "회원가입 요청 값이 올바르지 않습니다.") String buildingNumber,

        @Schema(description = "아파트 호수", example = "1203")
        @NotBlank(message = "회원가입 요청 값이 올바르지 않습니다.") String unitNumber
) {}