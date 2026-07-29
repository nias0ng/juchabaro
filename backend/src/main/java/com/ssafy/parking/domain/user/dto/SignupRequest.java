package com.ssafy.parking.domain.user.dto;

import jakarta.validation.constraints.NotBlank;

public record SignupRequest(
        @NotBlank(message = "회원가입 요청 값이 올바르지 않습니다.") String loginId,
        @NotBlank(message = "회원가입 요청 값이 올바르지 않습니다.") String password,
        @NotBlank(message = "회원가입 요청 값이 올바르지 않습니다.") String phoneNumber,
        @NotBlank(message = "회원가입 요청 값이 올바르지 않습니다.") String name,
        @NotBlank(message = "회원가입 요청 값이 올바르지 않습니다.") String buildingNumber,
        @NotBlank(message = "회원가입 요청 값이 올바르지 않습니다.") String unitNumber
) {}