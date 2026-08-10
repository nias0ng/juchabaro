package com.ssafy.parking.domain.user.dto;

import com.ssafy.parking.domain.user.entity.User;
import io.swagger.v3.oas.annotations.media.Schema;

import java.time.OffsetDateTime;
import java.time.ZoneId;

public record MeResponse(
        @Schema(description = "사용자 ID", example = "1")
        Long userId,

        @Schema(description = "로그인 아이디", example = "chaewon01")
        String loginId,

        @Schema(description = "전화번호", example = "01012345678")
        String phoneNumber,

        @Schema(description = "아파트 동 (관리자는 null 가능)", example = "101")
        String buildingNumber,

        @Schema(description = "아파트 호수 (관리자는 null 가능)", example = "1203")
        String unitNumber,

        @Schema(description = "이름", example = "김싸피")
        String name,

        @Schema(description = "사용자 권한", example = "RESIDENT")
        String role,

        @Schema(description = "계정 상태", example = "ACTIVE")
        String status,

        @Schema(description = "계정 생성 일시 (ISO 8601)", example = "2026-07-23T14:00:00+09:00")
        OffsetDateTime createdAt
) {
    public static MeResponse from(User user) {
        return new MeResponse(
                user.getId(),
                user.getLoginId(),
                user.getPhoneNumber(),
                user.getBuildingNumber(),
                user.getUnitNumber(),
                user.getName(),
                user.getRole().name(),
                user.getStatus().name(),
                user.getCreatedAt().atZone(ZoneId.of("Asia/Seoul")).toOffsetDateTime()
        );
    }
}