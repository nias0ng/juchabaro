package com.ssafy.parking.domain.move.dto;

import com.ssafy.parking.domain.move.entity.MoveRequest;
import org.springframework.data.domain.Page;

import java.util.List;
import java.util.Map;

public record MoveRequestListResponse(
        List<MoveRequestSummaryResponse> moveRequests,
        int page,
        int size,
        long totalElements,
        int totalPages
) {
    public static MoveRequestListResponse from(Page<MoveRequest> page, Map<Long, Integer> estimatedMinutesMap) {
        return new MoveRequestListResponse(
                page.getContent().stream()
                        .map(mr -> MoveRequestSummaryResponse.from(mr, estimatedMinutesMap.get(mr.getId())))
                        .toList(),
                page.getNumber(),
                page.getSize(),
                page.getTotalElements(),
                page.getTotalPages()
        );
    }
}