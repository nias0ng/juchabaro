package com.ssafy.parking.domain.admin.dto;

import java.util.List;

public record AdminHistoryResponse(
        List<AdminHistoryItem> history,
        int page, int size, long totalElements, int totalPages
) {}