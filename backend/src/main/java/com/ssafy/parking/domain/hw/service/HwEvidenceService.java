package com.ssafy.parking.domain.hw.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.common.storage.ImageStorageService;
import com.ssafy.parking.domain.hw.dto.EvidenceMetadata;
import com.ssafy.parking.domain.hw.dto.EvidenceUnavailableRequest;
import com.ssafy.parking.domain.hw.dto.HwPublicationAck;
import com.ssafy.parking.domain.parking.entity.EventImage;
import com.ssafy.parking.domain.parking.entity.EventImageType;
import com.ssafy.parking.domain.parking.entity.EvidenceAvailability;
import com.ssafy.parking.domain.parking.entity.ParkingEvent;
import com.ssafy.parking.domain.parking.repository.EventImageRepository;
import com.ssafy.parking.domain.parking.repository.ParkingEventRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.HashMap;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class HwEvidenceService {

    private static final long MAX_BYTES = 2L * 1024 * 1024; // 2 MiB

    private final ParkingEventRepository parkingEventRepository;
    private final EventImageRepository eventImageRepository;
    private final ImageStorageService imageStorageService;

    @Transactional
    public HwPublicationAck upload(String incidentId, MultipartFile file, EvidenceMetadata meta) {
        ParkingEvent event = parkingEventRepository.findByIncidentId(incidentId)
                .orElseThrow(() -> new BusinessException(ErrorCode.HW_INCIDENT_NOT_FOUND));

        EventImage dup = eventImageRepository.findByEvidenceId(meta.evidenceId()).orElse(null);
        if (dup != null) {
            return ack(meta.evidenceId(), meta.publicationRevision(), dup, "ALREADY_APPLIED");
        }

        if (file == null || file.isEmpty()) {
            throw new BusinessException(ErrorCode.HW_EVIDENCE_INVALID);
        }
        if (file.getSize() > MAX_BYTES) {
            throw new BusinessException(ErrorCode.HW_EVIDENCE_TOO_LARGE);
        }
        if (meta.byteSize() != null && meta.byteSize() != file.getSize()) {
            throw new BusinessException(ErrorCode.HW_EVIDENCE_INVALID);
        }
        verifyChecksum(file, meta.checksum());

        String url = imageStorageService.store(file, event.getId());
        EventImage img = EventImage.builder()
                .event(event)
                .imageUrl(url)
                .imageType(EventImageType.PARKING_STATE)
                .capturedAt(meta.capturedAt() != null ? toKst(meta.capturedAt()) : null)
                .evidenceId(meta.evidenceId())
                .publicationRevision(meta.publicationRevision())
                .availability(EvidenceAvailability.AVAILABLE)
                .checksum(meta.checksum())
                .byteSize(file.getSize())
                .build();
        eventImageRepository.save(img);
        return ack(meta.evidenceId(), meta.publicationRevision(), img, "APPLIED");
    }

    @Transactional
    public HwPublicationAck markUnavailable(String incidentId, EvidenceUnavailableRequest req) {
        ParkingEvent event = parkingEventRepository.findByIncidentId(incidentId)
                .orElseThrow(() -> new BusinessException(ErrorCode.HW_INCIDENT_NOT_FOUND));

        EventImage dup = eventImageRepository.findByEvidenceId(req.evidenceId()).orElse(null);
        if (dup != null) {
            return ack(req.evidenceId(), req.publicationRevision(), dup, "ALREADY_APPLIED");
        }

        EventImage img = EventImage.builder()
                .event(event)
                .imageUrl(null)
                .imageType(EventImageType.PARKING_STATE)
                .evidenceId(req.evidenceId())
                .publicationRevision(req.publicationRevision())
                .availability(EvidenceAvailability.UNAVAILABLE)
                .unavailableReason(req.reason())
                .checksum(req.checksum())
                .byteSize(req.byteSize())
                .build();
        eventImageRepository.save(img);
        return ack(req.evidenceId(), req.publicationRevision(), img, "APPLIED");
    }

    private HwPublicationAck ack(String evidenceId, Integer revision, EventImage img, String result) {
        Map<String, Object> corr = new HashMap<>();
        corr.put("imageId", img.getId());
        if (img.getImageUrl() != null) corr.put("imageUrl", img.getImageUrl());
        return new HwPublicationAck("EvidenceArtifact", evidenceId, revision, result, corr);
    }

    private void verifyChecksum(MultipartFile file, String checksum) {
        if (checksum == null || !checksum.startsWith("sha256:")) return; // 형식 아니면 검증 스킵
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(file.getBytes());
            StringBuilder sb = new StringBuilder();
            for (byte b : digest) sb.append(String.format("%02x", b));
            if (!checksum.substring(7).equalsIgnoreCase(sb.toString())) {
                throw new BusinessException(ErrorCode.HW_EVIDENCE_INVALID);
            }
        } catch (NoSuchAlgorithmException | IOException e) {
            throw new BusinessException(ErrorCode.HW_EVIDENCE_INVALID);
        }
    }

    private LocalDateTime toKst(OffsetDateTime t) {
        return t.atZoneSameInstant(ZoneId.of("Asia/Seoul")).toLocalDateTime();
    }
}