package com.ssafy.parking.domain.hw.dto;

import java.time.OffsetDateTime;

public record EvidenceMetadata(
        String evidenceId,
        Integer publicationRevision,
        OffsetDateTime capturedAt,
        String mimeType,
        Long byteSize,
        String checksum
) {}