package com.ssafy.parking.domain.move.repository;

import com.ssafy.parking.domain.move.entity.MoveRequestResponse;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.Collection;
import java.util.List;

public interface MoveRequestResponseRepository extends JpaRepository<MoveRequestResponse, Long> {

    List<MoveRequestResponse> findByRequest_IdOrderByRespondedAtAsc(Long requestId);

    List<MoveRequestResponse> findByRequest_IdInOrderByRespondedAtAsc(Collection<Long> requestIds);

    @Query("""
        select r.request.requestedAt, r.respondedAt
        from MoveRequestResponse r
        where r.responder.id = :userId and r.respondedAt >= :since
        """)
    List<Object[]> findResponseTimingsByResponder(
            @Param("userId") Long userId,
            @Param("since") LocalDateTime since);
}