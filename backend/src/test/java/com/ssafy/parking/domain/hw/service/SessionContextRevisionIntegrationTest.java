package com.ssafy.parking.domain.hw.service;

import com.ssafy.parking.domain.hw.dto.HwEntryRequest;
import com.ssafy.parking.domain.hw.dto.HwEntryResponse;
import com.ssafy.parking.domain.hw.dto.HwExitRequest;
import com.ssafy.parking.domain.hw.dto.HwPublicationAck;
import com.ssafy.parking.domain.hw.outbox.OutboxMessage;
import com.ssafy.parking.domain.hw.outbox.OutboxRepository;
import com.ssafy.parking.domain.hw.outbox.OutboxStatus;
import com.ssafy.parking.domain.parking.entity.ParkingSession;
import com.ssafy.parking.domain.parking.repository.ParkingSessionRepository;
import com.ssafy.parking.domain.user.entity.User;
import com.ssafy.parking.domain.user.entity.UserRole;
import com.ssafy.parking.domain.user.entity.UserStatus;
import com.ssafy.parking.domain.user.repository.UserRepository;
import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import com.ssafy.parking.domain.vehicle.entity.VehicleOwnerType;
import com.ssafy.parking.domain.vehicle.entity.VehicleStatus;
import com.ssafy.parking.domain.vehicle.repository.VehicleRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

@ActiveProfiles("test")
@SpringBootTest
@Transactional
class SessionContextRevisionIntegrationTest {

    private static final String PLATE_NUMBER = "12가3456";

    @Autowired
    private HwEntryService hwEntryService;

    @Autowired
    private HwTransitionService hwTransitionService;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private VehicleRepository vehicleRepository;

    @Autowired
    private ParkingSessionRepository parkingSessionRepository;

    @Autowired
    private OutboxRepository outboxRepository;

    @Test
    void allowEntryStartsDecisionAndContextAtSameRevision() {
        registerVehicle();

        String entryIdempotencyKey = "entry-" + UUID.randomUUID();

        HwEntryResponse response = hwEntryService.processEntry(
                entryIdempotencyKey,
                entryRequest()
        );

        ParkingSession session = parkingSessionRepository
                .findByIdempotencyKey(entryIdempotencyKey)
                .orElseThrow();

        assertThat(response.accessDecision()).isEqualTo("ALLOW");
        assertThat(response.decisionRevision()).isEqualTo(1);
        assertThat(response.sessionContext()).isNotNull();

        assertThat(session.getContextRevision()).isEqualTo(1);
        assertThat(response.sessionContext().sessionId())
                .isEqualTo(session.getId());
    }

    @Test
    void exitPublishesClosedWithNextContextRevision() {
        registerVehicle();

        String entryIdempotencyKey = "entry-" + UUID.randomUUID();

        HwEntryResponse entryResponse = hwEntryService.processEntry(
                entryIdempotencyKey,
                entryRequest()
        );

        Long sessionId = entryResponse.sessionContext().sessionId();

        HwPublicationAck exitAck = hwTransitionService.handleExit(
                "exit-" + UUID.randomUUID(),
                exitRequest(sessionId)
        );

        ParkingSession session = parkingSessionRepository
                .findById(sessionId)
                .orElseThrow();

        String expectedOutboxKey =
                "SessionContextUpdate:" + sessionId + ":2";

        OutboxMessage outbox = outboxRepository
                .findByIdempotencyKey(expectedOutboxKey)
                .orElseThrow();

        assertThat(exitAck.applicationResult()).isEqualTo("APPLIED");
        assertThat(session.getExitTime()).isNotNull();
        assertThat(session.getContextRevision()).isEqualTo(2);

        assertThat(outbox.getRevision()).isEqualTo(2);
        assertThat(outbox.getStatus()).isEqualTo(OutboxStatus.PENDING);
        assertThat(outbox.getPayload())
                .contains("\"contextRevision\":2")
                .contains("\"administrativeState\":\"CLOSED\"");
    }

    @Test
    void duplicateExitDoesNotIncreaseRevisionAgain() {
        registerVehicle();

        String entryIdempotencyKey = "entry-" + UUID.randomUUID();

        HwEntryResponse entryResponse = hwEntryService.processEntry(
                entryIdempotencyKey,
                entryRequest()
        );

        Long sessionId = entryResponse.sessionContext().sessionId();
        String exitIdempotencyKey = "exit-" + UUID.randomUUID();
        HwExitRequest exitRequest = exitRequest(sessionId);

        HwPublicationAck first = hwTransitionService.handleExit(
                exitIdempotencyKey,
                exitRequest
        );

        HwPublicationAck duplicate = hwTransitionService.handleExit(
                exitIdempotencyKey,
                exitRequest
        );

        ParkingSession session = parkingSessionRepository
                .findById(sessionId)
                .orElseThrow();

        assertThat(first.applicationResult()).isEqualTo("APPLIED");
        assertThat(duplicate.applicationResult())
                .isEqualTo("ALREADY_APPLIED");

        assertThat(session.getContextRevision()).isEqualTo(2);

        assertThat(
                outboxRepository.findByIdempotencyKey(
                        "SessionContextUpdate:" + sessionId + ":2"
                )
        ).isPresent();

        assertThat(
                outboxRepository.findByIdempotencyKey(
                        "SessionContextUpdate:" + sessionId + ":3"
                )
        ).isEmpty();
    }

    private void registerVehicle() {
        String suffix = UUID.randomUUID()
                .toString()
                .replace("-", "")
                .substring(0, 8);

        User user = userRepository.save(
                User.builder()
                        .loginId("revision-user-" + suffix)
                        .passwordHash("encoded-password")
                        .phoneNumber("01012345678")
                        .buildingNumber("101")
                        .unitNumber("1001")
                        .name("테스트 사용자")
                        .role(UserRole.RESIDENT)
                        .status(UserStatus.ACTIVE)
                        .build()
        );

        vehicleRepository.save(
                Vehicle.builder()
                        .user(user)
                        .plateNumber(PLATE_NUMBER)
                        .vehicleModel("테스트 차량")
                        .disabledVehicle(false)
                        .electric(false)
                        .ownerType(VehicleOwnerType.RESIDENT)
                        .status(VehicleStatus.ACTIVE)
                        .build()
        );
    }

    private HwEntryRequest entryRequest() {
        return new HwEntryRequest(
                "entry-attempt-" + UUID.randomUUID(),
                PLATE_NUMBER,
                0.98,
                OffsetDateTime.now(ZoneOffset.ofHours(9))
        );
    }

    private HwExitRequest exitRequest(Long sessionId) {
        return new HwExitRequest(
                sessionId,
                1,
                "physical-vehicle-1",
                OffsetDateTime.now(ZoneOffset.ofHours(9)),
                "JETSON_EXIT_CONFIRMED",
                "FULL_AREA_ABSENCE"
        );
    }
}
