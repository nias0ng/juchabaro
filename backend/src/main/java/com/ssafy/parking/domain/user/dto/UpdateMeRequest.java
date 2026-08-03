package com.ssafy.parking.domain.user.dto;

public record UpdateMeRequest(
        String name,            // 변경 시에만 전달 (선택)
        String currentPassword, // 비밀번호 변경 시 필수
        String newPassword      // 변경 시에만 전달 (선택)
) {}