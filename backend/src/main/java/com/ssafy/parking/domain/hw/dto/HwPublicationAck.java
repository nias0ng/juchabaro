package com.ssafy.parking.domain.hw.dto;

import java.util.Map;

public record HwPublicationAck(
        String aggregateType,
        String aggregateId,
        Integer publicationRevision,
        String applicationResult,   // APPLIED | ALREADY_APPLIED
        Map<String, Object> backendCorrelation
) {}