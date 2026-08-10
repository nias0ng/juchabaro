package com.ssafy.parking.domain.notification.dto;

import com.ssafy.parking.domain.move.entity.MoveRequest;
import com.ssafy.parking.domain.notification.entity.Notification;
import com.ssafy.parking.domain.parking.entity.EventImage;
import com.ssafy.parking.domain.parking.entity.ParkingEvent;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.List;

public record NotificationDetailResponse(
        Long notificationId,
        String notificationType,
        String title,
        String body,
        OffsetDateTime sentAt,
        EventInfo event,
        MoveRequestInfo moveRequest
) {
    public record EventInfo(
            Long eventId,
            String eventType,
            String reason,
            String eventStatus,
            OffsetDateTime detectedAt,
            List<ImageInfo> images
    ) {}

    public record ImageInfo(
            Long imageId,
            String imageType,
            String imageUrl,
            OffsetDateTime capturedAt
    ) {}

    public record MoveRequestInfo(
            Long requestId,
            String requestStatus,
            OffsetDateTime requestedAt,
            OffsetDateTime dueAt,
            int reminderCount
    ) {}

    public static NotificationDetailResponse from(Notification n, List<EventImage> images) {
        EventInfo eventInfo = null;
        if (n.getEvent() != null) {
            ParkingEvent e = n.getEvent();
            List<ImageInfo> imageInfos = images.stream()
                    .map(img -> new ImageInfo(
                            img.getId(),
                            img.getImageType().name(),
                            img.getImageUrl(),
                            (img.getCapturedAt() != null) ? toKst(img.getCapturedAt()) : null))
                    .toList();
            eventInfo = new EventInfo(
                    e.getId(), e.getEventType().name(), e.getReason(),
                    e.getEventStatus().name(), toKst(e.getDetectedAt()), imageInfos);
        }

        MoveRequestInfo mrInfo = null;
        if (n.getRequest() != null) {
            MoveRequest mr = n.getRequest();
            mrInfo = new MoveRequestInfo(
                    mr.getId(), mr.getRequestStatus().name(),
                    toKst(mr.getRequestedAt()),
                    (mr.getDueAt() != null) ? toKst(mr.getDueAt()) : null,
                    mr.getReminderCount());
        }

        return new NotificationDetailResponse(
                n.getId(), n.getNotificationType().name(),
                n.getTitle(), n.getBody(), toKst(n.getSentAt()),
                eventInfo, mrInfo);
    }

    private static OffsetDateTime toKst(LocalDateTime t) {
        return t.atZone(ZoneId.of("Asia/Seoul")).toOffsetDateTime();
    }
}