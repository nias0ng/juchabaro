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

    @Column(name = "image_url", nullable = false, length = 500)
    private String imageUrl;

    @Enumerated(EnumType.STRING)
    @Column(name = "image_type", nullable = false, length = 30)
    private EventImageType imageType;

    @Column(name = "captured_at")
    private LocalDateTime capturedAt;

    @Builder
    private EventImage(
            ParkingEvent event,
            String imageUrl,
            EventImageType imageType,
            LocalDateTime capturedAt
    ) {
        this.event = event;
        this.imageUrl = imageUrl;
        this.imageType = imageType;
        this.capturedAt = capturedAt;
    }
}