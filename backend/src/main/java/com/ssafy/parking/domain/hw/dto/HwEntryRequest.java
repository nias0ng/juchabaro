package com.ssafy.parking.domain.hw.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

import java.time.OffsetDateTime;

public record HwEntryRequest(
        @NotBlank String trackingId,
        @NotBlank String recognizedPlateNumber,
        Double ocrConfidence,                 // Pi가 보냄(참고용), 현재 판정엔 미사용
        @NotNull OffsetDateTime entryTime
) {}