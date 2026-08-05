package com.ssafy.parking.domain.admin.dto;

import java.util.List;

public record AdminEventListResponse(
        List<AdminEventSummary> events,
        int page, int size, long totalElements, int totalPages
) {}