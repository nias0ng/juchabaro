package com.ssafy.parking.domain.user.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;

public record LoginRequest(
        @Schema(description = "로그인 아이디", example = "chaewon01")
        @NotBlank(message = "로그인 요청 값이 올바르지 않습니다.") String loginId,

        @Schema(description = "비밀번호", example = "Password123!")
        @NotBlank(message = "로그인 요청 값이 올바르지 않습니다.") String password
) {}