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

    /**
     * 최초 입차 판정과 함께 생성되는 authoritative context의 revision.
     *
     * Jetson은 최초 ALLOW의 decisionRevision을 session contextRevision으로
     * 저장하므로 Backend의 ParkingSession도 동일한 revision에서 시작해야 한다.
     */
    private static final int INITIAL_DECISION_REVISION = 1;

    private final VehicleRepository vehicleRepository;
    private final ParkingSessionRepository parkingSessionRepository;
    private final EntryDecisionRepository entryDecisionRepository;

    @Value("${app.plate.review-distance}")
    private int reviewDistance;

    @Transactional
    public HwEntryResponse processEntry(String idempotencyKey, HwEntryRequest request) {
        String payloadHash = hashPayload(request);

        Optional<EntryDecision> existing =
                entryDecisionRepository.findByIdempotencyKey(idempotencyKey);

        if (existing.isPresent()) {
            EntryDecision receipt = existing.get();

            if (!receipt.getPayloadHash().equals(payloadHash)) {
                throw new BusinessException(ErrorCode.HW_ENTRY_CONFLICT);
            }

            return toResponse(receipt, true);
        }

        String normalized = PlateMatcher.normalize(request.recognizedPlateNumber());
        List<Vehicle> activeVehicles =
                vehicleRepository.findByStatus(VehicleStatus.ACTIVE);

        Vehicle best = null;
        int bestDist = Integer.MAX_VALUE;

        for (Vehicle vehicle : activeVehicles) {
            int distance = PlateMatcher.distance(
                    normalized,
                    PlateMatcher.normalize(vehicle.getPlateNumber())
            );

            if (distance < bestDist) {
                bestDist = distance;
                best = vehicle;
            }
        }

        AccessDecision decision;
        Long vehicleId = null;
        Long sessionId = null;

        if (best == null || bestDist > reviewDistance) {
            decision = AccessDecision.DENY;

        } else if (bestDist == 0) {
            decision = AccessDecision.ALLOW;

            LocalDateTime entryKst = request.entryTime()
                    .atZoneSameInstant(KST)
                    .toLocalDateTime();

            /*
             * 최초 authoritative context를 포함하는 ALLOW의 decisionRevision과
             * ParkingSession.contextRevision을 동일한 값으로 시작한다.
             *
             * 이후 ACTIVE 변경이나 CLOSED 전송에서는
             * SessionContextNotifier가 revision을 1씩 증가시킨다.
             */
            ParkingSession session = ParkingSession.builder()
                    .vehicle(best)
                    .recognizedPlateNumber(normalized)
                    .entryAttemptId(request.entryAttemptId())
                    .idempotencyKey(idempotencyKey)
                    .entryTime(entryKst)
                    .contextRevision(INITIAL_DECISION_REVISION)
                    .build();

            parkingSessionRepository.save(session);

            vehicleId = best.getId();
            sessionId = session.getId();

        } else {
            decision = AccessDecision.REVIEW;
            vehicleId = best.getId();
        }

        EntryDecision receipt = entryDecisionRepository.save(
                EntryDecision.builder()
                        .idempotencyKey(idempotencyKey)
                        .entryAttemptId(request.entryAttemptId())
                        .payloadHash(payloadHash)
                        .accessDecision(decision)
                        .decisionRevision(INITIAL_DECISION_REVISION)
                        .vehicleId(vehicleId)
                        .sessionId(sessionId)
                        .build()
        );

        return toResponse(receipt, false);
    }

    private HwEntryResponse toResponse(
            EntryDecision receipt,
            boolean duplicate
    ) {
        HwEntryResponse.SessionContext context = null;

        if (receipt.getAccessDecision() == AccessDecision.ALLOW
                && receipt.getSessionId() != null) {

            Vehicle vehicle = vehicleRepository
                    .findById(receipt.getVehicleId())
                    .orElseThrow(
                            () -> new BusinessException(ErrorCode.VEHICLE_NOT_FOUND)
                    );

            context = new HwEntryResponse.SessionContext(
                    receipt.getSessionId(),
                    vehicle.getId(),
                    vehicle.isDisabledVehicle(),
                    vehicle.isElectric()
            );
        }

        return new HwEntryResponse(
                receipt.getAccessDecision().name(),
                receipt.getEntryAttemptId(),
                receipt.getDecisionRevision(),
                duplicate,
                context
        );
    }

    private String hashPayload(HwEntryRequest request) {
        String canonical = String.join(
                "|",
                nullToEmpty(request.entryAttemptId()),
                nullToEmpty(request.recognizedPlateNumber()),
                request.ocrConfidence() == null
                        ? ""
                        : request.ocrConfidence().toString(),
                request.entryTime() == null
                        ? ""
                        : request.entryTime().toInstant().toString()
        );

        try {
            byte[] hash = MessageDigest
                    .getInstance("SHA-256")
                    .digest(canonical.getBytes(StandardCharsets.UTF_8));

            StringBuilder result = new StringBuilder(64);

            for (byte value : hash) {
                result.append(String.format("%02x", value));
            }

            return result.toString();

        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    private String nullToEmpty(String value) {
        return value == null ? "" : value;
    }
}