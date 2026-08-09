package com.ssafy.parking.domain.move.service;

import com.ssafy.parking.domain.move.entity.MoveRequest;
import com.ssafy.parking.domain.move.entity.MoveRequestStatus;
import com.ssafy.parking.domain.move.entity.MoveRequestType;
import com.ssafy.parking.domain.move.repository.MoveRequestRepository;
import com.ssafy.parking.domain.notification.entity.NotificationType;
import com.ssafy.parking.domain.notification.service.NotificationDispatcher;
import com.ssafy.parking.domain.parking.entity.ParkingEvent;
import com.ssafy.parking.domain.parking.entity.ParkingEventStatus;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

@Service
@RequiredArgsConstructor
public class ManualMoveRequestResolutionService {

    private static final List<MoveRequestStatus> ACTIVE_STATUSES = List.of(
            MoveRequestStatus.SENT,
            MoveRequestStatus.RESPONDED,
            MoveRequestStatus.REMINDER_SENT,
            MoveRequestStatus.NEED_ADMIN);

    private final MoveRequestRepository moveRequestRepository;
    private final NotificationDispatcher notificationDispatcher;

    @Transactional
    public int resolveAfterParkingStateChanged(Long sessionId, LocalDateTime occurredAt) {
        List<MoveRequest> targets = moveRequestRepository
                .findByEvent_Session_IdAndRequestTypeAndRequestStatusInAndRequestedAtLessThanEqual(
                        sessionId,
                        MoveRequestType.MANUAL,
                        ACTIVE_STATUSES,
                        occurredAt);

        int resolvedCount = 0;
        for (MoveRequest request : targets) {
            ParkingEvent event = request.getEvent();
            if (event.getEventStatus() == ParkingEventStatus.RESOLVED
                    || event.getEventStatus() == ParkingEventStatus.DISMISSED) {
                continue;
            }

            request.markCompleted();
            event.resolve(occurredAt);
            resolvedCount++;

            if (request.getRequester() != null) {
                notificationDispatcher.dispatch(
                        request.getRequester(),
                        NotificationType.EVENT_RESOLVED,
                        "차량 이동 확인",
                        "신고한 차량의 이동이 확인되어 요청이 완료되었습니다.",
                        event,
                        request,
                        occurredAt);
            }
        }
        return resolvedCount;
    }
}
