package com.ssafy.parking.domain.hw.dto;

import java.time.OffsetDateTime;

public record EvidenceUnavailableRequest(
        String evidenceId,
        Integer publicationRevision,
        String reason,
        OffsetDateTime unavailableAt,
        Long byteSize,
        String checksum
) {}