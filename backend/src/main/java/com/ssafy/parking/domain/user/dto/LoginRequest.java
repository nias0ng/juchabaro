package com.ssafy.parking.domain.user.dto;

import jakarta.validation.constraints.NotBlank;

public record LoginRequest(
        @NotBlank(message = "로그인 요청 값이 올바르지 않습니다.") String loginId,
        @NotBlank(message = "로그인 요청 값이 올바르지 않습니다.") String password
) {}