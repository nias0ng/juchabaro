package com.ssafy.parking.domain.hw.service;

import com.ssafy.parking.domain.hw.dto.HwTransitionRequest;
import com.ssafy.parking.domain.move.entity.MoveRequest;
import com.ssafy.parking.domain.move.entity.MoveRequestStatus;
import com.ssafy.parking.domain.move.entity.MoveRequestType;
import com.ssafy.parking.domain.move.repository.MoveRequestRepository;
import com.ssafy.parking.domain.parking.entity.ParkingEvent;
import com.ssafy.parking.domain.parking.entity.ParkingEventStatus;
import com.ssafy.parking.domain.parking.entity.ParkingEventType;
import com.ssafy.parking.domain.parking.entity.ParkingSession;
import com.ssafy.parking.domain.parking.entity.ParkingZone;
import com.ssafy.parking.domain.parking.entity.ParkingZoneStatus;
import com.ssafy.parking.domain.parking.entity.ParkingZoneType;
import com.ssafy.parking.domain.parking.repository.ParkingEventRepository;
import com.ssafy.parking.domain.parking.repository.ParkingSessionRepository;
import com.ssafy.parking.domain.parking.repository.ParkingZoneRepository;
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

import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

@ActiveProfiles("test")
@SpringBootTest
@Transactional
class ManualMoveRequestResolutionIntegrationTest {

    private static final ZoneId KST = ZoneId.of("Asia/Seoul");

    @Autowired
    private HwTransitionService hwTransitionService;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private VehicleRepository vehicleRepository;

    @Autowired
    private ParkingZoneRepository parkingZoneRepository;

    @Autowired
    private ParkingSessionRepository parkingSessionRepository;

    @Autowired
    private ParkingEventRepository parkingEventRepository;

    @Autowired
    private MoveRequestRepository moveRequestRepository;

    @Test
    void unparkedAfterManualReportCompletesRequestAndEvent() {
        Fixture fixture = createManualReport();
        LocalDateTime occurredAt = fixture.request().getRequestedAt().plusMinutes(1);

        hwTransitionService.handleTransition(
                "unparked-" + UUID.randomUUID(),
                transition(fixture.session(), occurredAt, "UNPARKED", null));

        assertResolved(fixture, occurredAt);
        assertThat(fixture.session().getZone()).isNull();
        assertThat(fixture.session().getParkedAt()).isNull();
        assertThat(fixture.session().getExitTime()).isNull();
    }

    @Test
    void assignedParkingAfterManualReportCompletesRequestAndEvent() {
        Fixture fixture = createManualReport();
        LocalDateTime occurredAt = fixture.request().getRequestedAt().plusMinutes(1);

        hwTransitionService.handleTransition(
                "parked-" + UUID.randomUUID(),
                transition(
                        fixture.session(),
                        occurredAt,
                        "PARKED",
                        new HwTransitionRequest.Assignment(
                                "ASSIGNED", fixture.zone().getHwZoneId(), null)));

        assertResolved(fixture, occurredAt);
        assertThat(fixture.session().getZone().getId()).isEqualTo(fixture.zone().getId());
        assertThat(fixture.session().getExitTime()).isNull();
    }

    @Test
    void transitionBeforeManualReportDoesNotCompleteIt() {
        Fixture fixture = createManualReport();
        LocalDateTime occurredAt = fixture.request().getRequestedAt().minusSeconds(1);

        hwTransitionService.handleTransition(
                "old-unparked-" + UUID.randomUUID(),
                transition(fixture.session(), occurredAt, "UNPARKED", null));

        assertThat(fixture.request().getRequestStatus()).isEqualTo(MoveRequestStatus.SENT);
        assertThat(fixture.event().getEventStatus()).isEqualTo(ParkingEventStatus.REQUESTED);
        assertThat(fixture.event().getResolvedAt()).isNull();
    }

    private Fixture createManualReport() {
        String suffix = UUID.randomUUID().toString().replace("-", "").substring(0, 8);
        User targetOwner = saveUser("target-" + suffix);
        User requester = saveUser("requester-" + suffix);

        Vehicle vehicle = vehicleRepository.save(Vehicle.builder()
                .user(targetOwner)
                .plateNumber("12가" + suffix.substring(0, 4))
                .vehicleModel("테스트 차량")
                .disabledVehicle(false)
                .electric(false)
                .ownerType(VehicleOwnerType.RESIDENT)
                .status(VehicleStatus.ACTIVE)
                .build());

        ParkingZone zone = parkingZoneRepository.save(ParkingZone.builder()
                .zoneNumber("A-" + suffix)
                .zoneType(ParkingZoneType.GENERAL)
                .floor("B1")
                .status(ParkingZoneStatus.ACTIVE)
                .hwZoneId(Math.abs(suffix.hashCode()))
                .build());

        LocalDateTime requestedAt = LocalDateTime.now().minusMinutes(1);
        ParkingSession session = parkingSessionRepository.save(ParkingSession.builder()
                .vehicle(vehicle)
                .zone(zone)
                .recognizedPlateNumber(vehicle.getPlateNumber())
                .entryAttemptId("entry-" + suffix)
                .entryTime(requestedAt.minusMinutes(10))
                .parkedAt(requestedAt.minusMinutes(5))
                .contextRevision(1)
                .build());

        ParkingEvent event = parkingEventRepository.save(ParkingEvent.builder()
                .session(session)
                .vehicle(vehicle)
                .zone(zone)
                .eventType(ParkingEventType.BAD_PARKING)
                .reason("수동 신고")
                .eventStatus(ParkingEventStatus.REQUESTED)
                .detectedAt(requestedAt)
                .build());

        MoveRequest request = moveRequestRepository.save(MoveRequest.builder()
                .event(event)
                .requester(requester)
                .targetVehicle(vehicle)
                .requestType(MoveRequestType.MANUAL)
                .requestStatus(MoveRequestStatus.SENT)
                .message("차량을 이동해 주세요.")
                .requestedAt(requestedAt)
                .build());

        return new Fixture(session, zone, event, request);
    }

    private User saveUser(String loginId) {
        return userRepository.save(User.builder()
                .loginId(loginId)
                .passwordHash("encoded-password")
                .phoneNumber("01012345678")
                .buildingNumber("101")
                .unitNumber("1001")
                .name("테스트 사용자")
                .role(UserRole.RESIDENT)
                .status(UserStatus.ACTIVE)
                .build());
    }

    private HwTransitionRequest transition(
            ParkingSession session,
            LocalDateTime occurredAt,
            String type,
            HwTransitionRequest.Assignment assignment
    ) {
        return new HwTransitionRequest(
                "episode-" + UUID.randomUUID(),
                "PARKED".equals(type) ? 1 : 2,
                type,
                "physical-vehicle-1",
                session.getId(),
                occurredAt.atZone(KST).toOffsetDateTime(),
                assignment);
    }

    private void assertResolved(Fixture fixture, LocalDateTime occurredAt) {
        assertThat(fixture.request().getRequestStatus()).isEqualTo(MoveRequestStatus.COMPLETED);
        assertThat(fixture.event().getEventStatus()).isEqualTo(ParkingEventStatus.RESOLVED);
        assertThat(fixture.event().getResolvedAt()).isEqualTo(occurredAt);
    }

    private record Fixture(
            ParkingSession session,
            ParkingZone zone,
            ParkingEvent event,
            MoveRequest request
    ) {}
}
