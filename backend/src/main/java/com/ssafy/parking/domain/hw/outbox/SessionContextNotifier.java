package com.ssafy.parking.domain.hw.outbox;

import com.ssafy.parking.domain.parking.entity.ParkingSession;
import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import com.ssafy.parking.domain.hw.outbox.OutboxService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.time.ZoneId;

@Service
@RequiredArgsConstructor
public class SessionContextNotifier {

    private static final ZoneId KST = ZoneId.of("Asia/Seoul");

    private final OutboxService outboxService;

    @Transactional
    public void publish(ParkingSession session, String administrativeState) {
        int revision = session.bumpContextRevision();
        Vehicle v = session.getVehicle();

        SessionContextUpdatePayload payload = new SessionContextUpdatePayload(
                session.getId(),
                session.getEntryAttemptId(),
                revision,
                administrativeState,
                OffsetDateTime.now(KST),
                new SessionContextUpdatePayload.SessionContext(
                        v.getId(), v.isDisabledVehicle(), v.isElectric()));

        outboxService.enqueue(
                OutboxCommandType.SESSION_CONTEXT_UPDATE,
                String.valueOf(session.getId()),
                revision,
                payload,
                null);   // API 5는 deadline 없음
    }
}