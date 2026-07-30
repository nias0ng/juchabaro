package com.ssafy.parking.domain.hw.service;

import com.ssafy.parking.common.util.PlateMatcher;
import com.ssafy.parking.domain.hw.dto.AccessDecision;
import com.ssafy.parking.domain.hw.dto.HwEntryRequest;
import com.ssafy.parking.domain.hw.dto.HwEntryResponse;
import com.ssafy.parking.domain.parking.entity.ParkingSession;
import com.ssafy.parking.domain.parking.repository.ParkingSessionRepository;
import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import com.ssafy.parking.domain.vehicle.entity.VehicleStatus;
import com.ssafy.parking.domain.vehicle.repository.VehicleRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.List;
import java.util.Optional;

@Service
@RequiredArgsConstructor
public class HwEntryService {

    private final VehicleRepository vehicleRepository;
    private final ParkingSessionRepository parkingSessionRepository;

    @Value("${app.plate.review-distance}")
    private int reviewDistance;

    @Transactional
    public HwEntryResponse processEntry(String idempotencyKey, HwEntryRequest request) {
        // 멱등: 같은 키로 이미 세션 생성됨 → 그대로 반환
        Optional<ParkingSession> existing = parkingSessionRepository.findByIdempotencyKey(idempotencyKey);
        if (existing.isPresent()) {
            ParkingSession s = existing.get();
            return HwEntryResponse.matched(AccessDecision.ALLOW, s.getVehicle(),
                    request.trackingId(), s.getId(), true);
        }

        // 편집거리 매칭 (등록 ACTIVE 차량 중 최소 거리)
        String normalized = PlateMatcher.normalize(request.recognizedPlateNumber());
        List<Vehicle> activeVehicles = vehicleRepository.findByStatus(VehicleStatus.ACTIVE);

        Vehicle best = null;
        int bestDist = Integer.MAX_VALUE;
        for (Vehicle v : activeVehicles) {
            int d = PlateMatcher.distance(normalized, PlateMatcher.normalize(v.getPlateNumber()));
            if (d < bestDist) {
                bestDist = d;
                best = v;
            }
        }

        // 판정
        if (best == null || bestDist > reviewDistance) {
            return HwEntryResponse.denied(request.trackingId());        // DENY
        }
        if (bestDist == 0) {
            LocalDateTime entryKst = request.entryTime()
                    .atZoneSameInstant(ZoneId.of("Asia/Seoul")).toLocalDateTime();
            ParkingSession session = ParkingSession.builder()
                    .vehicle(best)
                    .recognizedPlateNumber(normalized)
                    .trackingId(request.trackingId())
                    .idempotencyKey(idempotencyKey)
                    .entryTime(entryKst)
                    .build();
            parkingSessionRepository.save(session);
            return HwEntryResponse.matched(AccessDecision.ALLOW, best,
                    request.trackingId(), session.getId(), false);     // ALLOW
        }
        return HwEntryResponse.matched(AccessDecision.REVIEW, best,
                request.trackingId(), null, false);                    // REVIEW (1글자 차이)
    }
}