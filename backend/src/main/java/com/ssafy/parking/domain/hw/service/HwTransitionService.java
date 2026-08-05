package com.ssafy.parking.domain.hw.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.domain.hw.dto.HwExitRequest;
import com.ssafy.parking.domain.hw.dto.HwPublicationAck;
import com.ssafy.parking.domain.hw.dto.HwTransitionRequest;
import com.ssafy.parking.domain.hw.outbox.SessionContextNotifier;
import com.ssafy.parking.domain.parking.entity.ParkingSession;
import com.ssafy.parking.domain.parking.entity.ParkingZone;
import com.ssafy.parking.domain.parking.repository.ParkingSessionRepository;
import com.ssafy.parking.domain.parking.repository.ParkingZoneRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;

@Service
@RequiredArgsConstructor
public class HwTransitionService {

    private final ParkingSessionRepository parkingSessionRepository;
    private final ParkingZoneRepository parkingZoneRepository;
    private final InboundIdempotencyService inboundIdempotencyService;
    private final SessionContextNotifier sessionContextNotifier;

    @Transactional
    public HwPublicationAck handleTransition(String idempotencyKey, HwTransitionRequest req) {
        inboundIdempotencyService.record("PARKING_TRANSITION", idempotencyKey, req);

        ParkingSession session = parkingSessionRepository.findById(req.sessionId())
                .orElseThrow(() -> new BusinessException(ErrorCode.PARKING_SESSION_NOT_FOUND));

        LocalDateTime occurred = toKstLocal(req.occurredAt());
        Map<String, Object> corr = new HashMap<>();
        corr.put("sessionId", session.getId());
        String result;

        if ("PARKED".equals(req.transitionType())) {
            ParkingZone zone = null;
            HwTransitionRequest.Assignment a = req.assignment();
            if (a != null && "ASSIGNED".equals(a.state())) {
                zone = parkingZoneRepository.findByHwZoneId(a.zoneId())
                        .orElseThrow(() -> new BusinessException(ErrorCode.HW_ZONE_NOT_FOUND));
            }
            boolean already = session.getParkedAt() != null && sameZone(session.getZone(), zone);
            session.assignZone(zone, occurred);
            if (zone != null) corr.put("zoneNumber", zone.getZoneNumber());
            result = already ? "ALREADY_APPLIED" : "APPLIED";

        } else if ("UNPARKED".equals(req.transitionType())) {
            boolean already = session.getZone() == null && session.getParkedAt() == null;
            session.unassign();
            result = already ? "ALREADY_APPLIED" : "APPLIED";

        } else {
            throw new BusinessException(ErrorCode.HW_TRANSITION_INVALID);
        }

        return new HwPublicationAck(
                "ParkingEpisode", req.parkingEpisodeId(),
                req.publicationRevision(), result, corr);
    }

    @Transactional
    public HwPublicationAck handleExit(String idempotencyKey, HwExitRequest req) {
        inboundIdempotencyService.record("SESSION_EXIT", idempotencyKey, req);

        ParkingSession session = parkingSessionRepository.findById(req.sessionId())
                .orElseThrow(() -> new BusinessException(ErrorCode.PARKING_SESSION_NOT_FOUND));

        String result;
        if (session.getExitTime() != null) {
            result = "ALREADY_APPLIED";
        } else {
            session.markExit(toKstLocal(req.occurredAt()));
            sessionContextNotifier.publish(session, "CLOSED");
            result = "APPLIED";
        }

        Map<String, Object> corr = new HashMap<>();
        corr.put("sessionId", session.getId());
        return new HwPublicationAck(
                "Session", String.valueOf(session.getId()),
                req.publicationRevision(), result, corr);
    }

    private boolean sameZone(ParkingZone a, ParkingZone b) {
        Long ai = (a != null) ? a.getId() : null;
        Long bi = (b != null) ? b.getId() : null;
        return Objects.equals(ai, bi);
    }

    private LocalDateTime toKstLocal(OffsetDateTime t) {
        return t.atZoneSameInstant(ZoneId.of("Asia/Seoul")).toLocalDateTime();
    }
}