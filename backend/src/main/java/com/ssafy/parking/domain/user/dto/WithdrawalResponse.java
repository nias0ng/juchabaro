package com.ssafy.parking.domain.user.dto;

import java.time.OffsetDateTime;

public record WithdrawalResponse(
        Long userId,
        String status,
        OffsetDateTime withdrawnAt
) {}