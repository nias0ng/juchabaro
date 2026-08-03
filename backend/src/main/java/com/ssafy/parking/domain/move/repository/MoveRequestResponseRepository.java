package com.ssafy.parking.domain.move.repository;

import com.ssafy.parking.domain.move.entity.MoveRequestResponse;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface MoveRequestResponseRepository extends JpaRepository<MoveRequestResponse, Long> {
    List<MoveRequestResponse> findByRequest_IdOrderByRespondedAtAsc(Long requestId);
    List<MoveRequestResponse> findByRequest_IdInOrderByRespondedAtAsc(java.util.Collection<Long> requestIds);
}