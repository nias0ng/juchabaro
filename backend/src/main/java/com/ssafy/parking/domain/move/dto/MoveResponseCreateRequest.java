package com.ssafy.parking.domain.move.dto;

import com.ssafy.parking.domain.move.entity.MoveResponseType;

public record MoveResponseCreateRequest(
        MoveResponseType responseType,
        Integer estimatedMinutes
) {}