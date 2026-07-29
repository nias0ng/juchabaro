package com.ssafy.parking.domain.user.dto;

import com.ssafy.parking.domain.user.entity.User;

public record SignupResponse(
        Long userId,
        String phoneNumber,
        String name,
        String role,
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