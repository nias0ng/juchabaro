package com.ssafy.parking.domain.parking.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.domain.parking.dto.*;
import com.ssafy.parking.domain.parking.entity.ParkingZone;
import com.ssafy.parking.domain.parking.entity.ParkingZoneStatus;
import com.ssafy.parking.domain.parking.repository.ParkingZoneRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class ZoneService {

    private final ParkingZoneRepository parkingZoneRepository;

    // hw_zone_id → 화면 표시 코드(zone_number). 물리 배치/디자인에 맞춰 FE와 확정한 값.
    // 맵에 없는 id는 generateZoneNumber의 fallback(타입+id)으로 생성.
    private static final Map<Integer, String> ZONE_CODE = Map.ofEntries(
            Map.entry(1, "EV-01"),
            Map.entry(2, "A-02"),
            Map.entry(3, "A-03"),
            Map.entry(4, "D-04"),
            Map.entry(5, "D-05"),
            Map.entry(6, "D-06"),
            Map.entry(7, "AISLE-07"),
            Map.entry(8, "ENTRY-08"),
            Map.entry(9, "EXIT-09")
    );

    @Transactional
    public ZoneImportResult importZones(ZoneImportRequest request) {
        int created = 0;
        int updated = 0;

        for (ZoneImportRequest.ZoneItem item : request.zones()) {
            Integer allowedMinutes = (item.allowedDurationSeconds() != null)
                    ? Math.round(item.allowedDurationSeconds() / 60f)
                    : null;

            String geometry = buildGeometryJson(
                    item.polygon(), item.chargerClass(),
                    item.egressZoneIds(), request.calibrationReference());

            ParkingZone existing = parkingZoneRepository.findByHwZoneId(item.zoneId()).orElse(null);
            if (existing != null) {
                existing.updateDefinition(
                        item.zoneType(), item.zoneId(), item.entryExitRole(),
                        allowedMinutes, geometry, request.floor());
                updated++;
            } else {
                String zoneNumber = generateZoneNumber(
                        item.zoneType(), item.entryExitRole(), item.zoneId());
                ParkingZone zone = ParkingZone.builder()
                        .zoneNumber(zoneNumber)
                        .zoneType(item.zoneType())
                        .hwZoneId(item.zoneId())
                        .entryExitRole(item.entryExitRole())
                        .allowedMinutes(allowedMinutes)
                        .geometryData(geometry)
                        .floor(request.floor())
                        .status(ParkingZoneStatus.ACTIVE)
                        .build();
                parkingZoneRepository.save(zone);
                created++;
            }
        }
        return new ZoneImportResult(request.zones().size(), created, updated);
    }

    private String generateZoneNumber(
            com.ssafy.parking.domain.parking.entity.ParkingZoneType type,
            com.ssafy.parking.domain.parking.entity.EntryExitRole role,
            Integer hwZoneId) {
        String mapped = ZONE_CODE.get(hwZoneId);
        if (mapped != null) {
            return mapped;
        }
        // 고정맵에 없는 id는 타입+id로 폴백 생성
        String prefix = switch (type) {
            case EV_CHARGING -> "EV";
            case GENERAL -> "GEN";
            case DISABLED -> "DIS";
            case AISLE -> "AISLE";
            case ENTRY_EXIT -> (role != null) ? role.name() : "EE";  // ENTRY / EXIT
        };
        return prefix + "-" + hwZoneId;
    }

    @Transactional(readOnly = true)
    public ZoneListResponse getZones() {
        return ZoneListResponse.from(parkingZoneRepository.findAllByOrderByHwZoneIdAsc());
    }

    // geometry_data에 저장할 JSON을 수동 조립 (Jackson 의존 없이 안전하게)
    private String buildGeometryJson(
            List<List<Double>> polygon, String chargerClass,
            List<Integer> egressZoneIds, String calibrationReference) {
        return "{\"coordSystem\":\"normalized\""
                + ",\"polygon\":" + polygonToJson(polygon)
                + ",\"chargerClass\":" + jsonString(chargerClass)
                + ",\"egressZoneIds\":" + intArrayToJson(egressZoneIds)
                + ",\"calibrationReference\":" + jsonString(calibrationReference)
                + "}";
    }

    private String polygonToJson(List<List<Double>> polygon) {
        if (polygon == null) return "[]";
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < polygon.size(); i++) {
            List<Double> p = polygon.get(i);
            if (i > 0) sb.append(",");
            sb.append("[").append(p.get(0)).append(",").append(p.get(1)).append("]");
        }
        return sb.append("]").toString();
    }

    private String intArrayToJson(List<Integer> nums) {
        if (nums == null) return "[]";
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < nums.size(); i++) {
            if (i > 0) sb.append(",");
            sb.append(nums.get(i));
        }
        return sb.append("]").toString();
    }

    private String jsonString(String v) {
        if (v == null) return "null";
        return "\"" + v.replace("\\", "\\\\").replace("\"", "\\\"") + "\"";
    }

    @Transactional
    public ZoneResponse updateZone(Long zoneId, ZoneUpdateRequest request) {
        ParkingZone zone = parkingZoneRepository.findById(zoneId)
                .orElseThrow(() -> new BusinessException(ErrorCode.ZONE_NOT_FOUND));
        zone.applyAdminEdit(request.zoneNumber(), request.zoneType(), request.allowedMinutes());
        return ZoneResponse.from(zone);
    }
}