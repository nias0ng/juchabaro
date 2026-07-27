package com.ssafy.parking.domain.move.entity;

import com.ssafy.parking.common.entity.BaseCreatedEntity;
import com.ssafy.parking.domain.user.entity.User;
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
@Table(name = "move_request_responses")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class MoveRequestResponse extends BaseCreatedEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "response_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "request_id", nullable = false)
    private MoveRequest request;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "responder_user_id", nullable = false)
    private User responder;

    @Enumerated(EnumType.STRING)
    @Column(name = "response_type", nullable = false, length = 30)
    private MoveResponseType responseType;

    @Column(name = "estimated_minutes")
    private Integer estimatedMinutes;

    @Column(name = "responded_at", nullable = false)
    private LocalDateTime respondedAt;

    @Builder
    private MoveRequestResponse(
            MoveRequest request,
            User responder,
            MoveResponseType responseType,
            Integer estimatedMinutes,
            LocalDateTime respondedAt
    ) {
        this.request = request;
        this.responder = responder;
        this.responseType = responseType;
        this.estimatedMinutes = estimatedMinutes;
        this.respondedAt = respondedAt;
    }
}