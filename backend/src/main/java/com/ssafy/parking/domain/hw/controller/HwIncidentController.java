package com.ssafy.parking.domain.hw.controller;

import com.ssafy.parking.common.response.ApiResponse;
import com.ssafy.parking.domain.hw.dto.HwIncidentTransitionRequest;
import com.ssafy.parking.domain.hw.dto.HwPublicationAck;
import com.ssafy.parking.domain.hw.service.HwEvidenceService;
import com.ssafy.parking.domain.hw.service.HwIncidentService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.ssafy.parking.domain.hw.dto.EvidenceMetadata;
import com.ssafy.parking.domain.hw.dto.EvidenceUnavailableRequest;
import com.ssafy.parking.domain.hw.service.HwEvidenceService;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.multipart.MultipartFile;

@Tag(name = "HW-사건", description = "Jetson 위반 사건 전이 API (X-HW-API-Key)")
@SecurityRequirement(name = "hwApiKey")
@RestController
@RequestMapping("/hw/parking-events")
@RequiredArgsConstructor
public class HwIncidentController {

    private final HwIncidentService hwIncidentService;
    private final HwEvidenceService hwEvidenceService;

    @Operation(summary = "사건 전이(OPEN/RESOLVE)", description = "Jetson이 확정한 위반 사건의 개시/해소를 반영합니다.")
    @PostMapping("/transitions")
    public ResponseEntity<ApiResponse<HwPublicationAck>> transition(
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody HwIncidentTransitionRequest request
    ) {
        HwPublicationAck ack = hwIncidentService.handle(idempotencyKey, request);
        return ResponseEntity.ok(ApiResponse.success(HttpStatus.OK, "사건 전이가 적용되었습니다.", ack));
    }

    @Operation(summary = "증거 이미지 업로드", description = "사건의 증거 정지 이미지를 업로드합니다.")
    @PostMapping(value = "/{incidentId}/evidence", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<ApiResponse<HwPublicationAck>> uploadEvidence(
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @PathVariable String incidentId,
            @RequestPart("file") MultipartFile file,
            @RequestPart("metadata") EvidenceMetadata metadata
    ) {
        HwPublicationAck ack = hwEvidenceService.upload(incidentId, file, metadata);
        return ResponseEntity.ok(ApiResponse.success(HttpStatus.OK, "증거가 업로드되었습니다.", ack));
    }

    @Operation(summary = "증거 제공 불가 통보", description = "저장 압박 등으로 증거를 제공할 수 없음을 기록합니다.")
    @PostMapping("/{incidentId}/evidence-unavailable")
    public ResponseEntity<ApiResponse<HwPublicationAck>> evidenceUnavailable(
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @PathVariable String incidentId,
            @RequestBody EvidenceUnavailableRequest request
    ) {
        HwPublicationAck ack = hwEvidenceService.markUnavailable(incidentId, request);
        return ResponseEntity.ok(ApiResponse.success(HttpStatus.OK, "증거 제공 불가가 기록되었습니다.", ack));
    }
}