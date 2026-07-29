package com.ssafy.parking.domain.user.dto;

public record LoginResponse(
        String accessToken,
        String tokenType,
        long expiresIn,
        Long userId,
        String name,
        String role
) {}