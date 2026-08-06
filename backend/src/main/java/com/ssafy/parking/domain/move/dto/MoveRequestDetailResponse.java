package com.ssafy.parking.domain.move.dto;

import com.ssafy.parking.domain.move.entity.MoveRequest;
import com.ssafy.parking.domain.move.entity.MoveRequestResponse;
import com.ssafy.parking.domain.notification.entity.Notification;
import com.ssafy.parking.domain.parking.entity.EventImage;
import com.ssafy.parking.domain.parking.entity.ParkingEvent;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.List;

public record MoveRequestDetailResponse(
        Long requestId,
        String requestType,
        String requestStatus,
        String message,
        OffsetDateTime requestedAt,
        OffsetDateTime dueAt,
        RequesterInfo requester,
        TargetVehicleInfo targetVehicle,
        EventInfo event,
        List<ResponseInfo> responses,
        List<HistoryInfo> history
) {
    public record RequesterInfo(Long userId, String name) {}

    public record TargetVehicleInfo(Long vehicleId, String plateNumber) {}

    public record ImageInfo(Long imageId, String imageType, String imageUrl) {}

    public record EventInfo(
            Long eventId,
            String eventType,
            String zoneNumber,
            List<ImageInfo> images
    ) {}

    public record ResponseInfo(
            Long responseId,
            String responseType,
            Integer estimatedMinutes,
            OffsetDateTime respondedAt
    ) {}

    public record HistoryInfo(String notificationType, OffsetDateTime sentAt) {}

    public static MoveRequestDetailResponse from(
            MoveRequest mr,
            List<EventImage> images,
            List<MoveRequestResponse> responses,
            List<Notification> history
    ) {
        RequesterInfo requester = (mr.getRequester() != null)
                ? new RequesterInfo(mr.getRequester().getId(), mr.getRequester().getName())
                : null;

        TargetVehicleInfo targetVehicle = new TargetVehicleInfo(
                mr.getTargetVehicle().getId(),
                mr.getTargetVehicle().getPlateNumber()
        );

        ParkingEvent e = mr.getEvent();
        String zoneNumber = (e.getZone() != null) ? e.getZone().getZoneNumber() : null;
        List<ImageInfo> imageInfos = images.stream()
                .map(img -> new ImageInfo(img.getId(), img.getImageType().name(), img.getImageUrl()))
                .toList();
        EventInfo eventInfo = new EventInfo(
                e.getId(),
                e.getEventType().name(),
                zoneNumber,
                imageInfos
        );

        List<ResponseInfo> responseInfos = responses.stream()
                .map(r -> new ResponseInfo(
                        r.getId(),
                        r.getResponseType().name(),
                        r.getEstimatedMinutes(),
                        toKst(r.getRespondedAt())
                ))
                .toList();

        List<HistoryInfo> historyInfos = history.stream()
                .map(n -> new HistoryInfo(n.getNotificationType().name(), toKst(n.getSentAt())))
                .toList();

        return new MoveRequestDetailResponse(
                mr.getId(),
                mr.getRequestType().name(),
                mr.getRequestStatus().name(),
                mr.getMessage(),
                toKst(mr.getRequestedAt()),
                (mr.getDueAt() != null) ? toKst(mr.getDueAt()) : null,
                requester,
                targetVehicle,
                eventInfo,
                responseInfos,
                historyInfos
        );
    }

    private static OffsetDateTime toKst(LocalDateTime t) {
        return t.atZone(ZoneId.of("Asia/Seoul")).toOffsetDateTime();
    }
}