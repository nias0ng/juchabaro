package com.ssafy.parking.domain.hw.outbox;

import com.ssafy.parking.domain.move.entity.MoveRequest;
import com.ssafy.parking.domain.parking.entity.ParkingEvent;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.ssafy.parking.domain.hw.outbox.OutboxService;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.List;

@Service
@RequiredArgsConstructor
public class MoveVerificationNotifier {

    private static final ZoneId KST = ZoneId.of("Asia/Seoul");

    private final OutboxService outboxService;

    @Value("${app.jetson.verify-window-seconds:120}")
    private long verifyWindowSeconds;

    @Transactional
    public void publish(MoveRequest mr) {
        ParkingEvent event = mr.getEvent();
        String incidentId = event.getIncidentId();
        if (incidentId == null || incidentId.isBlank()) {
            return;   // Jetson 감지 사건이 아니면 재확인 대상 아님(수동 신고 등)
        }

        int attempt = mr.bumpVerificationAttempt();
        LocalDateTime now = LocalDateTime.now();
        LocalDateTime deadlineLocal = now.plusSeconds(verifyWindowSeconds);

        MoveVerificationPayload payload = new MoveVerificationPayload(
                mr.getId(),
                attempt,
                List.of(incidentId),
                now.atZone(KST).toOffsetDateTime(),
                deadlineLocal.atZone(KST).toOffsetDateTime());

        outboxService.enqueue(
                OutboxCommandType.MOVE_VERIFICATION,
                String.valueOf(mr.getId()),
                attempt,
                payload,
                deadlineLocal);   // ← API 11만 deadline 설정(지나면 EXPIRED)
    }
}