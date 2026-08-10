package com.ssafy.parking.domain.move.dto;

import com.ssafy.parking.domain.move.entity.MoveRequest;
import com.ssafy.parking.domain.parking.entity.EventImage;
import com.ssafy.parking.domain.parking.entity.ParkingEvent;

import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.List;

public record MoveRequestCreateResponse(
        Long eventId,
        Long requestId,
        Long targetVehicleId,
        String requestType,
        String requestStatus,
        int reminderCount,
        List<ImageInfo> images,
        OffsetDateTime requestedAt
) {
    public record ImageInfo(Long imageId, String imageUrl, String imageType) {
        public static ImageInfo from(EventImage img) {
            return new ImageInfo(img.getId(), img.getImageUrl(), img.getImageType().name());
        }
    }

    public static MoveRequestCreateResponse from(ParkingEvent event, MoveRequest request, List<EventImage> images) {
        return new MoveRequestCreateResponse(
                event.getId(),
                request.getId(),
                request.getTargetVehicle().getId(),
                request.getRequestType().name(),
                request.getRequestStatus().name(),
                request.getReminderCount(),
                images.stream().map(ImageInfo::from).toList(),
                request.getRequestedAt().atZone(ZoneId.of("Asia/Seoul")).toOffsetDateTime()
        );
    }
}