import { useCallback, useEffect, useState } from 'react';

import type { MoveResponseType } from '@/features/move-request/api/types';
import {
  toRequestCompletedDisplay,
  toRequestDetailDisplay,
  toRequestEscalationDisplay,
  toRequestOverdueDisplay,
  toRequestWaitingDisplay,
} from '@/features/move-request/utils/move-request';

import { useCountdown } from './use-countdown';
import { useMoveRequestDetail } from './use-move-request-detail';
import { useMoveRequestResponse } from './use-move-request-response';

export type RequestDetailViewMode = 'requester' | 'recipient';

/**
 * request-detail-screen이 어떤 화면(E-11~E-16)을 그려야 하는지 결정하는 데 필요한 상태를 전부 계산한다.
 * requestStatus 하나만으로는 부족한 경우가 있어(REMINDER_SENT는 무응답/약속어김 두 상황을 가리킴,
 * RESPONDED는 dueAt이 지났는지에 따라 대기중/미이동으로 갈림) 여러 값을 조합해서 판단한다.
 */
export function useRequestDetailViewModel(
  requestId: number | null,
  viewMode: RequestDetailViewMode = 'recipient',
) {
  const { detail, isLoading, isRefreshing, error, refetch } = useMoveRequestDetail(requestId);
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

  const showResponseActions =
    viewMode === 'recipient' &&
    (detail?.requestStatus === 'SENT' || isReminderSentNoResponse);
  // 충전구역 초과 점유/장애인 구역 위반은 AI가 자동 감지한 위반이라 "몇 분 후 이동" 같은 응답을 받을 사람이 없다.
  // 대신 감지 시점부터 흐른 시간과 관리사무소 자동 전송 안내만 보여준다.
  const isAutoEscalationType =
    detail?.event.eventType === 'EV_OVERSTAY' || detail?.event.eventType === 'DISABLED_ZONE_VIOLATION';
  const occupancyCountdown = useCountdown(showResponseActions ? detail?.requestedAt ?? null : null);

  const latestResponse = detail?.responses[detail.responses.length - 1] ?? null;
  const latestReminderAt = detail
    ? [...detail.history].reverse().find((item) => item.notificationType === 'REMINDER')?.sentAt ?? null
    : null;
  const countdown = useCountdown(
    isWaiting ? detail?.dueAt ?? null : null,
    isWaiting ? latestResponse?.respondedAt ?? null : null,
  );
  // RESPONDED 상태인데 dueAt이 지난 경우(E-14) — 아직 재알림은 안 나갔지만 약속 시간을 넘김.
  const isOverdueWaiting = isWaiting && countdown.isOverdue;
  const showWaitingView = isWaiting && !isOverdueWaiting && !showDetail;
  const showOverdueView = isOverdueWaiting && !showDetail;
  // 받은 사람은 무응답 재알림 이후에도 응답할 수 있어야 하고, 이관 완료 뒤에는
  // 응답 버튼 없는 기존 상세 화면에서 이관 안내를 본다. 보낸 사람만 이관 타임라인을 유지한다.
  const showEscalationView =
    (viewMode === 'requester' && isNeedAdmin) ||
    isReminderSentOverdue ||
    (viewMode === 'requester' && isReminderSentNoResponse);

  const waitingDisplay = showWaitingView && detail ? toRequestWaitingDisplay(detail) : null;
  const completedDisplay = isCompleted && detail ? toRequestCompletedDisplay(detail) : null;
  const overdueDisplay = showOverdueView && detail ? toRequestOverdueDisplay(detail) : null;
  const escalationDisplay = showEscalationView && detail ? toRequestEscalationDisplay(detail) : null;
  const escalationCountdown = useCountdown(
    isReminderSent ? escalationDisplay?.escalationDueAt ?? null : null,
    latestReminderAt,
  );

  const respond = useCallback(
    async (responseType: MoveResponseType, estimatedMinutes: number | null) => {
      // 상세 캐시 갱신은 useMoveRequestResponse의 mutation onSuccess가 처리한다(refetch 왕복을 기다리지 않고 즉시 반영).
      const result = await submit({ responseType, estimatedMinutes });
      // 호출한 쪽(request-detail-body)이 성공 여부를 보고 F-02(응답 완료)로 이동할지 판단할 수 있게 그대로 돌려준다.
      return result;
    },
    [submit],
  );

  return {
    detail,
    viewMode,
    display,
    isLoading,
    isRefreshing,
    error,
    refetch,
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
    showEscalationView,
    waitingDisplay,
    completedDisplay,
    overdueDisplay,
    escalationDisplay,
    escalationCountdown,
    isSubmitting,
    submitError,
    respond,
  };
}

export type RequestDetailViewModel = ReturnType<typeof useRequestDetailViewModel>;
