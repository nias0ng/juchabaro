package com.ssafy.parking.domain.move.service;

import com.ssafy.parking.domain.move.entity.MoveRequest;
import com.ssafy.parking.domain.move.entity.MoveRequestStatus;
import com.ssafy.parking.domain.parking.entity.ParkingEventStatus;
import com.ssafy.parking.domain.move.repository.MoveRequestRepository;
import com.ssafy.parking.domain.notification.entity.NotificationType;
import com.ssafy.parking.domain.hw.outbox.MoveVerificationNotifier;
import com.ssafy.parking.domain.notification.service.NotificationDispatcher;
import lombok.RequiredArgsConstructor;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Set;

@Component
@RequiredArgsConstructor
public class MoveRequestScheduler {

    private static final Set<MoveRequestStatus> TERMINAL = Set.of(
            MoveRequestStatus.COMPLETED, MoveRequestStatus.CANCELLED, MoveRequestStatus.NEED_ADMIN);

    private final MoveRequestRepository moveRequestRepository;
    private final NotificationDispatcher notificationDispatcher;
    private final MoveVerificationNotifier moveVerificationNotifier;

    @Scheduled(fixedDelay = 60_000) // 1분 주기
    @Transactional
    public void runOverdueScan() {
        LocalDateTime now = LocalDateTime.now();
        sendReminders(now);
        escalateToAdmin(now);
    }

    // 재알림 1회: 무응답(requestedAt+1h) 또는 응답시각(dueAt) 경과
    private void sendReminders(LocalDateTime now) {
        LocalDateTime sentThreshold = now.minusHours(1);
        List<MoveRequest> targets = moveRequestRepository.findReminderTargets(
                MoveRequestStatus.SENT, MoveRequestStatus.RESPONDED, sentThreshold, now);
        for (MoveRequest mr : targets) {
            mr.markReminderSent(now);
            notificationDispatcher.dispatch(
                    mr.getTargetVehicle().getUser(),
                    NotificationType.REMINDER,
                    "차량 이동 재요청",
                    "아직 이동이 확인되지 않았습니다. 차량 이동을 다시 요청드립니다.",
                    mr.getEvent(), mr, now);
            moveVerificationNotifier.publish(mr);
        }
    }

    // 재알림 후 1h 미해결 → 관리자(NEED_ADMIN)
    private void escalateToAdmin(LocalDateTime now) {
        LocalDateTime escalateThreshold = now.minusHours(1);
        List<MoveRequest> targets = moveRequestRepository.findEscalationTargets(escalateThreshold, TERMINAL);
        for (MoveRequest mr : targets) {
            mr.markNeedAdmin();
            mr.getEvent().changeStatus(ParkingEventStatus.NEED_ADMIN);
        }
    }
}