package com.ssafy.parking.domain.admin.repository;

import com.ssafy.parking.domain.admin.entity.AdminActionLog;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.List;

public interface AdminActionLogRepository extends JpaRepository<AdminActionLog, Long> {

    List<AdminActionLog> findByEvent_IdOrderByCreatedAtDesc(Long eventId);

    @Query("""
        select l from AdminActionLog l
        where l.createdAt >= :from and l.createdAt < :to
          and (:actionType is null or l.actionType = :actionType)
        order by l.createdAt desc
        """)
    Page<AdminActionLog> findForHistory(@Param("from") LocalDateTime from,
                                        @Param("to") LocalDateTime to,
                                        @Param("actionType") String actionType,
                                        Pageable pageable);
}