package com.ssafy.parking.domain.hw.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

import java.time.OffsetDateTime;

public record HwEntryRequest(
        @NotBlank String entryAttemptId,
        @NotBlank String recognizedPlateNumber,
        Double ocrConfidence,
        @NotNull OffsetDateTime entryTime
) {}