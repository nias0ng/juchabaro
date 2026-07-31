package com.ssafy.parking.domain.notification.dto;

import com.ssafy.parking.domain.notification.entity.Notification;
import org.springframework.data.domain.Page;

import java.util.List;

public record NotificationListResponse(
        List<NotificationSummaryResponse> notifications,
        int page,
        int size,
        long totalElements,
        int totalPages
) {
    public static NotificationListResponse from(Page<Notification> page) {
        return new NotificationListResponse(
                page.getContent().stream().map(NotificationSummaryResponse::from).toList(),
                page.getNumber(),
                page.getSize(),
                page.getTotalElements(),
                page.getTotalPages()
        );
    }
}