package com.ssafy.parking.domain.user.dto;

import io.swagger.v3.oas.annotations.media.Schema;

public record LoginResponse(
        @Schema(description = "JWT 액세스 토큰", example = "eyJhbGciOiJIUzI1NiJ9...")
        String accessToken,

        @Schema(description = "토큰 유형", example = "Bearer")
        String tokenType,

        @Schema(description = "액세스 토큰 만료 시간(초)", example = "3600")
        long expiresIn,

        @Schema(description = "사용자 ID", example = "1")
        Long userId,

        @Schema(description = "이름", example = "김싸피")
        String name,

        @Schema(description = "사용자 권한", example = "RESIDENT")
        String role
) {}