package com.ssafy.parking.common.entity;

import com.ssafy.parking.common.config.JpaAuditingConfig;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.data.jpa.test.autoconfigure.DataJpaTest;
import org.springframework.boot.jpa.test.autoconfigure.TestEntityManager;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.ActiveProfiles;

import static org.assertj.core.api.Assertions.assertThat;

@ActiveProfiles("test")
@DataJpaTest
@Import(JpaAuditingConfig.class)
class BaseEntityTest {

    @Autowired
    private TestEntityManager entityManager;

    @Test
    void fillCreatedAtAndUpdatedAtWhenPersisted() {
        AuditingTestEntity entity = new AuditingTestEntity();

        entityManager.persistAndFlush(entity);

        assertThat(entity.getCreatedAt()).isNotNull();
        assertThat(entity.getUpdatedAt()).isNotNull();
    }
}

@Entity
class AuditingTestEntity extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    protected AuditingTestEntity() {
    }
}