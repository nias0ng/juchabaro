package com.ssafy.parking.domain.notification.dto;

import com.ssafy.parking.domain.notification.entity.Notification;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;

public record NotificationSummaryResponse(
        Long notificationId,
        Long eventId,
        Long requestId,
        String notificationType,
        String title,
        String body,
        OffsetDateTime sentAt
) {
    public static NotificationSummaryResponse from(Notification n) {
        Long eventId = (n.getEvent() != null) ? n.getEvent().getId() : null;
        Long requestId = (n.getRequest() != null) ? n.getRequest().getId() : null;
        return new NotificationSummaryResponse(
                n.getId(), eventId, requestId,
                n.getNotificationType().name(),
                n.getTitle(), n.getBody(),
                toKst(n.getSentAt())
        );
    }

    private static OffsetDateTime toKst(LocalDateTime t) {
        return t.atZone(ZoneId.of("Asia/Seoul")).toOffsetDateTime();
    }
}