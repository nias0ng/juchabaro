package com.ssafy.parking.domain.notification.repository;

import com.ssafy.parking.domain.notification.entity.Notification;
import com.ssafy.parking.domain.notification.entity.NotificationType;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface NotificationRepository extends JpaRepository<Notification, Long> {

    // TODO(N+1 최적화): 매핑 시 event/request(nullable ToOne) lazy 접근으로 N+1 발생.
    //   필요 시 @EntityGraph(attributePaths = {"event", "request"}) 적용.
    @Query("""
        select n from Notification n
        where n.user.id = :userId
          and (:type is null or n.notificationType = :type)
        """)
    Page<Notification> findByUser(@Param("userId") Long userId,
                                  @Param("type") NotificationType type,
                                  Pageable pageable);
}