package com.ssafy.parking.domain.hw.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.domain.hw.dto.HwIncidentTransitionRequest;
import com.ssafy.parking.domain.hw.dto.HwPublicationAck;
import com.ssafy.parking.domain.notification.entity.NotificationType;
import com.ssafy.parking.domain.notification.service.NotificationDispatcher;
import com.ssafy.parking.domain.parking.entity.ParkingEvent;
import com.ssafy.parking.domain.parking.entity.ParkingEventStatus;
import com.ssafy.parking.domain.parking.entity.ParkingSession;
import com.ssafy.parking.domain.parking.entity.ParkingZone;
import com.ssafy.parking.domain.parking.repository.ParkingEventRepository;
import com.ssafy.parking.domain.parking.repository.ParkingSessionRepository;
import com.ssafy.parking.domain.parking.repository.ParkingZoneRepository;
import com.ssafy.parking.domain.parking.util.RuleCodeMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.HashMap;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class HwIncidentService {

    private final ParkingEventRepository parkingEventRepository;
    private final ParkingSessionRepository parkingSessionRepository;
    private final ParkingZoneRepository parkingZoneRepository;

    private final NotificationDispatcher notificationDispatcher;

    @Transactional
    public HwPublicationAck handle(HwIncidentTransitionRequest req) {
        if ("OPEN".equals(req.transitionType())) {
            return open(req);
        } else if ("RESOLVE".equals(req.transitionType())) {
            return resolve(req);
        }
        throw new BusinessException(ErrorCode.HW_INCIDENT_INVALID);
    }

    private HwPublicationAck open(HwIncidentTransitionRequest req) {
        ParkingEvent existing = parkingEventRepository.findByIncidentId(req.incidentId()).orElse(null);
        if (existing != null) {
            return ack(req, existing, "ALREADY_APPLIED");
        }
        if (req.sessionId() == null) {              // 파일럿: 세션 바인딩 필수
            throw new BusinessException(ErrorCode.HW_INCIDENT_INVALID);
        }
        ParkingSession session = parkingSessionRepository.findById(req.sessionId())
                .orElseThrow(() -> new BusinessException(ErrorCode.PARKING_SESSION_NOT_FOUND));
        ParkingZone zone = (req.zoneId() != null)
                ? parkingZoneRepository.findByHwZoneId(req.zoneId()).orElse(null) : null;

        ParkingEvent event = ParkingEvent.builder()
                .session(session)
                .vehicle(session.getVehicle())
                .zone(zone)
                .eventType(RuleCodeMapper.toEventType(req.ruleCode()))
                .reason(req.ruleCode())
                .eventStatus(ParkingEventStatus.DETECTED)
                .detectedAt(toKst(req.occurredAt()))
                .incidentId(req.incidentId())
                .publicationRevision(req.publicationRevision())
                .ruleCode(req.ruleCode())
                .physicalVehicleId(req.physicalVehicleId())
                .entryAttemptId(req.entryAttemptId())
                .build();
        parkingEventRepository.save(event);

        if ("EV_OVERSTAY".equals(req.ruleCode())) {
            notificationDispatcher.dispatch(
                    session.getVehicle().getUser(),
                    NotificationType.EV_OVERSTAY,
                    "전기차 충전구역 초과",
                    "충전구역 허용 시간을 초과했습니다. 차량 이동을 부탁드립니다.",
                    event, null, toKst(req.occurredAt()));
        }

        return ack(req, event, "APPLIED");
    }

    private HwPublicationAck resolve(HwIncidentTransitionRequest req) {
        ParkingEvent event = parkingEventRepository.findByIncidentId(req.incidentId())
                .orElseThrow(() -> new BusinessException(ErrorCode.HW_INCIDENT_NOT_FOUND));
        if (event.getEventStatus() == ParkingEventStatus.RESOLVED) {
            return ack(req, event, "ALREADY_APPLIED");
        }
        event.resolve(toKst(req.occurredAt()));
        return ack(req, event, "APPLIED");
    }

    private HwPublicationAck ack(HwIncidentTransitionRequest req, ParkingEvent event, String result) {
        Map<String, Object> corr = new HashMap<>();
        corr.put("eventId", event.getId());
        return new HwPublicationAck(
                "Incident", req.incidentId(), req.publicationRevision(), result, corr);
    }

    private LocalDateTime toKst(OffsetDateTime t) {
        return t.atZoneSameInstant(ZoneId.of("Asia/Seoul")).toLocalDateTime();
    }
}