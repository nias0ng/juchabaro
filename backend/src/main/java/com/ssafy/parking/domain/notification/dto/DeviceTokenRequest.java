package com.ssafy.parking.domain.notification.dto;

import jakarta.validation.constraints.NotBlank;

public record DeviceTokenRequest(
        @NotBlank String token,
        String platform
) {}