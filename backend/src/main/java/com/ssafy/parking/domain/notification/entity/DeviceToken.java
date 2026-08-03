package com.ssafy.parking.domain.notification.entity;

import com.ssafy.parking.common.entity.BaseEntity;
import com.ssafy.parking.domain.user.entity.User;
import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@Entity
@Table(name = "device_tokens",
        uniqueConstraints = @UniqueConstraint(name = "uk_device_tokens_token", columnNames = "token"))
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class DeviceToken extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "device_token_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Column(name = "token", nullable = false, length = 512)
    private String token;

    @Column(name = "platform", length = 20)
    private String platform;   // IOS | ANDROID | WEB (선택)

    @Builder
    private DeviceToken(User user, String token, String platform) {
        this.user = user;
        this.token = token;
        this.platform = platform;
    }

    // 다른 유저가 쓰던 토큰이면 현재 로그인 유저로 재바인딩(기기 공유/재로그인 대비)
    public void rebind(User user, String platform) {
        this.user = user;
        this.platform = platform;
    }
}