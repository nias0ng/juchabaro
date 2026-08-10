package com.ssafy.parking.domain.parking.service;

import com.ssafy.parking.domain.parking.dto.ParkingSessionListResponse;
import com.ssafy.parking.domain.parking.dto.ParkingSessionResponse;
import com.ssafy.parking.domain.parking.dto.ParkingZoneSummaryResponse;
import com.ssafy.parking.domain.parking.dto.SpotResponse;
import com.ssafy.parking.domain.parking.entity.ParkingEventStatus;
import com.ssafy.parking.domain.parking.entity.ParkingSession;
import com.ssafy.parking.domain.parking.entity.ParkingZone;
import com.ssafy.parking.domain.parking.entity.ParkingZoneStatus;
import com.ssafy.parking.domain.parking.entity.ParkingZoneType;
import com.ssafy.parking.domain.parking.repository.ParkingEventRepository;
import com.ssafy.parking.domain.parking.repository.ParkingSessionRepository;
import com.ssafy.parking.domain.parking.repository.ParkingZoneRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class ParkingStatusService {

    private static final Set<ParkingEventStatus> ACTIVE_VIOLATION = Set.of(
            ParkingEventStatus.DETECTED, ParkingEventStatus.REQUESTED, ParkingEventStatus.NEED_ADMIN);
    private static final Set<ParkingZoneType> PARKABLE_TYPES = Set.of(
            ParkingZoneType.GENERAL, ParkingZoneType.DISABLED, ParkingZoneType.EV_CHARGING);

    private final ParkingSessionRepository parkingSessionRepository;
    private final ParkingZoneRepository parkingZoneRepository;
    private final ParkingEventRepository parkingEventRepository;

    @Transactional(readOnly = true)
    public ParkingSessionListResponse getMySessions(Long userId) {
        List<ParkingSession> sessions = parkingSessionRepository
                .findByVehicle_User_IdAndExitTimeIsNullOrderByEntryTimeDesc(userId);
        Set<Long> violationIds = parkingEventRepository.findActiveViolationSessionIds(ACTIVE_VIOLATION);

        List<ParkingSessionResponse> items = sessions.stream()
                .map(s -> ParkingSessionResponse.of(s, violationIds.contains(s.getId())))
                .toList();
        return new ParkingSessionListResponse(items);
    }

    @Transactional(readOnly = true)
    public ParkingZoneSummaryResponse getSummary() {
        List<ParkingZone> zones = parkingZoneRepository
                .findByZoneTypeInAndStatusOrderByHwZoneIdAsc(PARKABLE_TYPES, ParkingZoneStatus.ACTIVE);
        List<ParkingSession> active = parkingSessionRepository.findByExitTimeIsNull();
        Set<Long> violationIds = parkingEventRepository.findActiveViolationSessionIds(ACTIVE_VIOLATION);

        Map<Long, ParkingSession> sessionByZone = new HashMap<>();
        for (ParkingSession s : active) {
            if (s.getZone() != null) {
                sessionByZone.putIfAbsent(s.getZone().getId(), s);
            }
        }

        List<SpotResponse> spots = zones.stream().map(z -> {
            ParkingSession s = sessionByZone.get(z.getId());
            String status;
            if (s == null) {
                status = "EMPTY";
            } else {
                status = violationIds.contains(s.getId()) ? "VIOLATION" : "OCCUPIED";
            }
            return new SpotResponse(
                    z.getId(), z.getZoneNumber(), z.getZoneType().name(),
                    z.getGeometryData(), status);
        }).toList();

        int total = spots.size();
        int occupied = (int) spots.stream().filter(sp -> !"EMPTY".equals(sp.occupancyStatus())).count();
        int violation = (int) spots.stream().filter(sp -> "VIOLATION".equals(sp.occupancyStatus())).count();
        int available = total - occupied;
        int rate = (total == 0) ? 0 : Math.round(occupied * 100f / total);
        String floor = zones.isEmpty() ? null : zones.get(0).getFloor();

        return new ParkingZoneSummaryResponse(
                floor, total, occupied, available, violation, rate, congestionLevel(rate), spots);
    }

    private String congestionLevel(int rate) {
        if (rate < 40) return "LOW";
        if (rate < 70) return "MEDIUM";
        return "HIGH";
    }
}