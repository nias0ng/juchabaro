package com.ssafy.parking.domain.user.dto;

import com.ssafy.parking.domain.user.entity.User;
import io.swagger.v3.oas.annotations.media.Schema;

public record SignupResponse(
        @Schema(description = "생성된 사용자 ID", example = "1")
        Long userId,

        @Schema(description = "전화번호", example = "01012345678")
        String phoneNumber,

        @Schema(description = "이름", example = "김싸피")
        String name,

        @Schema(description = "사용자 권한", example = "RESIDENT")
        String role,

        @Schema(description = "계정 상태", example = "ACTIVE")
        String status
) {
    public static SignupResponse from(User user) {
        return new SignupResponse(
                user.getId(),
                user.getPhoneNumber(),
                user.getName(),
                user.getRole().name(),
                user.getStatus().name()
        );
    }
}