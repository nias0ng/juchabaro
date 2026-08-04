package com.ssafy.parking.domain.hw.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.common.util.PlateMatcher;
import com.ssafy.parking.domain.hw.dto.AccessDecision;
import com.ssafy.parking.domain.hw.dto.HwEntryRequest;
import com.ssafy.parking.domain.hw.dto.HwEntryResponse;
import com.ssafy.parking.domain.hw.entity.EntryDecision;
import com.ssafy.parking.domain.hw.repository.EntryDecisionRepository;
import com.ssafy.parking.domain.parking.entity.ParkingSession;
import com.ssafy.parking.domain.parking.repository.ParkingSessionRepository;
import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import com.ssafy.parking.domain.vehicle.entity.VehicleStatus;
import com.ssafy.parking.domain.vehicle.repository.VehicleRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.List;
import java.util.Optional;

@Service
@RequiredArgsConstructor
public class HwEntryService {

    private static final ZoneId KST = ZoneId.of("Asia/Seoul");

    private final VehicleRepository vehicleRepository;
    private final ParkingSessionRepository parkingSessionRepository;
    private final EntryDecisionRepository entryDecisionRepository;

    @Value("${app.plate.review-distance}")
    private int reviewDistance;

    @Transactional
    public HwEntryResponse processEntry(String idempotencyKey, HwEntryRequest request) {
        String payloadHash = hashPayload(request);

        // 멱등: 같은 키로 이미 판정 리시트 존재
        Optional<EntryDecision> existing = entryDecisionRepository.findByIdempotencyKey(idempotencyKey);
        if (existing.isPresent()) {
            EntryDecision receipt = existing.get();
            if (!receipt.getPayloadHash().equals(payloadHash)) {
                throw new BusinessException(ErrorCode.HW_ENTRY_CONFLICT);   // 같은 키 + 다른 본문 → 409
            }
            return toResponse(receipt, true);                              // 동일 재요청 → 저장된 판정 재응답
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
        AccessDecision decision;
        Long vehicleId = null;
        Long sessionId = null;

        if (best == null || bestDist > reviewDistance) {
            decision = AccessDecision.DENY;
        } else if (bestDist == 0) {
            decision = AccessDecision.ALLOW;
            LocalDateTime entryKst = request.entryTime()
                    .atZoneSameInstant(KST).toLocalDateTime();
            ParkingSession session = ParkingSession.builder()
                    .vehicle(best)
                    .recognizedPlateNumber(normalized)
                    .entryAttemptId(request.entryAttemptId())
                    .idempotencyKey(idempotencyKey)
                    .entryTime(entryKst)
                    .build();
            parkingSessionRepository.save(session);
            vehicleId = best.getId();
            sessionId = session.getId();
        } else {
            decision = AccessDecision.REVIEW;          // 1글자 차이 → 검토 후보 기록만
            vehicleId = best.getId();
        }

        EntryDecision receipt = entryDecisionRepository.save(EntryDecision.builder()
                .idempotencyKey(idempotencyKey)
                .entryAttemptId(request.entryAttemptId())
                .payloadHash(payloadHash)
                .accessDecision(decision)
                .decisionRevision(1)
                .vehicleId(vehicleId)
                .sessionId(sessionId)
                .build());

        return toResponse(receipt, false);
    }

    private HwEntryResponse toResponse(EntryDecision r, boolean duplicate) {
        HwEntryResponse.SessionContext ctx = null;
        if (r.getAccessDecision() == AccessDecision.ALLOW && r.getSessionId() != null) {
            Vehicle v = vehicleRepository.findById(r.getVehicleId())
                    .orElseThrow(() -> new BusinessException(ErrorCode.VEHICLE_NOT_FOUND));
            ctx = new HwEntryResponse.SessionContext(
                    r.getSessionId(), v.getId(), v.isDisabledVehicle(), v.isElectric());
        }
        return new HwEntryResponse(
                r.getAccessDecision().name(),
                r.getEntryAttemptId(),
                r.getDecisionRevision(),
                duplicate,
                ctx);
    }

    private String hashPayload(HwEntryRequest req) {
        String canonical = String.join("|",
                nz(req.entryAttemptId()),
                nz(req.recognizedPlateNumber()),
                req.ocrConfidence() == null ? "" : req.ocrConfidence().toString(),
                req.entryTime() == null ? "" : req.entryTime().toInstant().toString());
        try {
            byte[] h = MessageDigest.getInstance("SHA-256")
                    .digest(canonical.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(64);
            for (byte b : h) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);   // SHA-256은 항상 존재
        }
    }

    private String nz(String s) {
        return s == null ? "" : s;
    }
}