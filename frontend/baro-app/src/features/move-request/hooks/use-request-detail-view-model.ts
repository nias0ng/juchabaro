import { useCallback, useEffect, useState } from 'react';

import type { MoveResponseType } from '@/features/move-request/api/types';
import {
  toRequestCompletedDisplay,
  toRequestDetailDisplay,
  toRequestOverdueDisplay,
  toRequestReminderDisplay,
  toRequestWaitingDisplay,
} from '@/features/move-request/utils/move-request';

import { useCountdown } from './use-countdown';
import { useMoveRequestDetail } from './use-move-request-detail';
import { useMoveRequestResponse } from './use-move-request-response';

/**
 * request-detail-screen이 어떤 화면(E-11~E-16)을 그려야 하는지 결정하는 데 필요한 상태를 전부 계산한다.
 * requestStatus 하나만으로는 부족한 경우가 있어(REMINDER_SENT는 무응답/약속어김 두 상황을 가리킴,
 * RESPONDED는 dueAt이 지났는지에 따라 대기중/미이동으로 갈림) 여러 값을 조합해서 판단한다.
 */
export function useRequestDetailViewModel(requestId: number | null) {
  const { detail, isLoading, error, applyResponse } = useMoveRequestDetail(requestId);
  const { submit, isSubmitting, errorMessage: submitError } = useMoveRequestResponse(requestId);
  const display = detail ? toRequestDetailDisplay(detail) : null;

  const isCompleted = detail?.requestStatus === 'COMPLETED';
  const isWaiting = detail?.requestStatus === 'RESPONDED';
  const hasResponded = detail ? detail.responses.length > 0 : false;
  // REMINDER_SENT는 두 가지 다른 상황을 가리킬 수 있다: 아예 무응답이었거나(A), 응답은 했는데 약속을 어겼거나(B).
  // responses가 있는지로 구분한다 — dueAt이 있다는 건 이미 WILL_MOVE로 응답했었다는 뜻이기 때문.
  const isReminderSent = detail?.requestStatus === 'REMINDER_SENT';
  const isReminderSentNoResponse = isReminderSent && !hasResponded;
  const isReminderSentOverdue = isReminderSent && hasResponded;
  const isNeedAdmin = detail?.requestStatus === 'NEED_ADMIN';

  // "요청 상세 보기"를 눌러서 대기/미이동 화면 대신 상세(E-11 레이아웃, 응답 버튼 없음)를 보고 있는 상태.
  const [showDetail, setShowDetail] = useState(false);
  useEffect(() => {
    setShowDetail(false);
  }, [requestId]);

  const showResponseActions = detail?.requestStatus === 'SENT' || isReminderSentNoResponse;
  // 충전구역 초과 점유/장애인 구역 위반은 AI가 자동 감지한 위반이라 "몇 분 후 이동" 같은 응답을 받을 사람이 없다.
  // 대신 감지 시점부터 흐른 시간과 관리사무소 자동 전송 안내만 보여준다.
  const isAutoEscalationType =
    detail?.event.eventType === 'EV_OVERSTAY' || detail?.event.eventType === 'DISABLED_ZONE_VIOLATION';
  const occupancyCountdown = useCountdown(showResponseActions ? detail?.requestedAt ?? null : null);

  const latestResponse = detail?.responses[detail.responses.length - 1] ?? null;
  const countdown = useCountdown(
    isWaiting ? detail?.dueAt ?? null : null,
    isWaiting ? latestResponse?.respondedAt ?? null : null,
  );
  // RESPONDED 상태인데 dueAt이 지난 경우(E-14) — 아직 재알림은 안 나갔지만 약속 시간을 넘김.
  const isOverdueWaiting = isWaiting && countdown.isOverdue;
  const showWaitingView = isWaiting && !isOverdueWaiting && !showDetail;
  const showOverdueView = isOverdueWaiting && !showDetail;

  const waitingDisplay = showWaitingView && detail ? toRequestWaitingDisplay(detail) : null;
  const completedDisplay = isCompleted && detail ? toRequestCompletedDisplay(detail) : null;
  const overdueDisplay = showOverdueView && detail ? toRequestOverdueDisplay(detail) : null;
  const reminderDisplay = isReminderSentOverdue && detail ? toRequestReminderDisplay(detail) : null;

  const respond = useCallback(
    async (responseType: MoveResponseType, estimatedMinutes: number | null) => {
      // refetch()로 다시 조회하면 그 왕복 시간만큼 카운트다운이 이미 흐른 채로 시작되니,
      // 서버가 이 응답 자체에서 돌려준 결과를 바로 반영한다.
      const result = await submit({ responseType, estimatedMinutes });
      if (result) applyResponse(result);
      // 호출한 쪽(request-detail-body)이 성공 여부를 보고 F-02(응답 완료)로 이동할지 판단할 수 있게 그대로 돌려준다.
      return result;
    },
    [submit, applyResponse],
  );

  return {
    detail,
    display,
    isLoading,
    error,
    isCompleted,
    isWaiting,
    hasResponded,
    isReminderSentNoResponse,
    isReminderSentOverdue,
    isNeedAdmin,
    showDetail,
    setShowDetail,
    showResponseActions,
    isAutoEscalationType,
    occupancyElapsedLabel: occupancyCountdown.elapsedLabel,
    countdown,
    isOverdueWaiting,
    showWaitingView,
    showOverdueView,
    waitingDisplay,
    completedDisplay,
    overdueDisplay,
    reminderDisplay,
    isSubmitting,
    submitError,
    respond,
  };
}

export type RequestDetailViewModel = ReturnType<typeof useRequestDetailViewModel>;
