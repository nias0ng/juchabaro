package com.ssafy.parking.domain.user.entity;

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
import jakarta.persistence.UniqueConstraint;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Getter
@Entity
@Table(
        name = "user_consents",
        uniqueConstraints = {
                @UniqueConstraint(
                        name = "uk_user_consents_user_type_version",
                        columnNames = {
                                "user_id",
                                "consent_type",
                                "consent_version"
                        }
                )
        }
)
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class UserConsent extends BaseCreatedEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "consent_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Enumerated(EnumType.STRING)
    @Column(name = "consent_type", nullable = false, length = 30)
    private ConsentType consentType;

    @Column(name = "consent_version", nullable = false, length = 20)
    private String consentVersion;

    @Column(name = "agreed_at", nullable = false)
    private LocalDateTime agreedAt;

    @Builder
    private UserConsent(
            User user,
            ConsentType consentType,
            String consentVersion,
            LocalDateTime agreedAt
    ) {
        this.user = user;
        this.consentType = consentType;
        this.consentVersion = consentVersion;
        this.agreedAt = agreedAt;
    }
}