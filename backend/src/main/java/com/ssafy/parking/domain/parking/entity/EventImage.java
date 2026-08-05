package com.ssafy.parking.domain.parking.entity;

import com.ssafy.parking.common.entity.BaseCreatedEntity;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Getter
@Entity
@Table(name = "event_images")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class EventImage extends BaseCreatedEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "image_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "event_id", nullable = false)
    private ParkingEvent event;

    @Column(name = "image_url", length = 500)
    private String imageUrl;

    @Enumerated(EnumType.STRING)
    @Column(name = "image_type", nullable = false, length = 30)
    private EventImageType imageType;

    @Column(name = "captured_at")
    private LocalDateTime capturedAt;

    @Column(name = "evidence_id", unique = true, length = 36)
    private String evidenceId;

    @Column(name = "publication_revision")
    private Integer publicationRevision;

    @Enumerated(EnumType.STRING)
    @Column(name = "availability", length = 20)
    private EvidenceAvailability availability;

    @Column(name = "unavailable_reason", length = 40)
    private String unavailableReason;

    @Column(name = "checksum", length = 100)
    private String checksum;

    @Column(name = "byte_size")
    private Long byteSize;

    @Builder
    private EventImage(
            ParkingEvent event,
            String imageUrl,
            EventImageType imageType,
            LocalDateTime capturedAt,
            String evidenceId,
            Integer publicationRevision,
            EvidenceAvailability availability,
            String unavailableReason,
            String checksum,
            Long byteSize
    ) {
        this.event = event;
        this.imageUrl = imageUrl;
        this.imageType = imageType;
        this.capturedAt = capturedAt;
        this.evidenceId = evidenceId;
        this.publicationRevision = publicationRevision;
        this.availability = availability;
        this.unavailableReason = unavailableReason;
        this.checksum = checksum;
        this.byteSize = byteSize;
    }
}