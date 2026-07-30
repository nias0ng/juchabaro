import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Text, View } from 'react-native';

import { Screen, ScreenHeader } from '@/components/ui';
import { RequestCompletedSection } from '@/features/move-request/components/request-completed/request-completed-section';
import { RequestDetailSection } from '@/features/move-request/components/request-detail/request-detail-section';
import { RequestHeaderRight } from '@/features/move-request/components/request-header-right';
import { RequestWaitingSection } from '@/features/move-request/components/request-waiting/request-waiting-section';
import { useCountdown } from '@/features/move-request/hooks/use-countdown';
import { useMoveRequestDetail } from '@/features/move-request/hooks/use-move-request-detail';
import { useMoveRequestResponse } from '@/features/move-request/hooks/use-move-request-response';
import {
  toRequestCompletedDisplay,
  toRequestDetailDisplay,
  toRequestWaitingDisplay,
} from '@/features/move-request/utils/move-request';
import { Palette } from '@/styles';

import { styles } from './request-detail-screen.styles';

const SUMMARY_TITLE = '고객님의 차량 이동을\n요청드립니다';
const REMINDER_MESSAGE = '응답이 없으면 한 시간 후에 한 번 더 알려드리고,\n그 이후에는 관리사무소로 전달합니다.';
const WAITING_GRADIENT = ['#ede9fd', '#f7f6fb'] as const;
const COMPLETED_GRADIENT = ['#eae7fb', '#f7f6fb'] as const;

export default function RequestDetailScreen() {
  const { requestId: requestIdParam } = useLocalSearchParams<{ requestId?: string }>();
  const requestId = requestIdParam ? Number(requestIdParam) : null;
  const normalizedRequestId = requestId !== null && !Number.isNaN(requestId) ? requestId : null;
  const { detail, isLoading, error, applyResponse } = useMoveRequestDetail(normalizedRequestId);
  const { submit, isSubmitting, errorMessage: submitError } = useMoveRequestResponse(normalizedRequestId);
  const display = detail ? toRequestDetailDisplay(detail) : null;

  // E-13: 차량 이동이 완료 처리된 상태.
  const isCompleted = detail?.requestStatus === 'COMPLETED';
  // E-12: 응답 완료 후 차량 이동을 기다리는 상태. 이 화면 하나가 requestStatus에 따라 다르게 그려진다.
  const isWaiting = detail?.requestStatus === 'RESPONDED';
  // "요청 상세 보기"를 눌러서 대기 화면 대신 상세(E-11 레이아웃, 응답 버튼 없음)를 보고 있는 상태.
  const [showDetail, setShowDetail] = useState(false);
  // 다른 요청으로 넘어갔는데 이전 요청에서 눌러둔 "상세 보기" 상태가 남아있지 않도록 초기화한다.
  useEffect(() => {
    setShowDetail(false);
  }, [normalizedRequestId]);
  const showWaitingView = isWaiting && !showDetail;
  const showResponseActions = !isWaiting;

  const latestResponse = detail?.responses[detail.responses.length - 1] ?? null;
  const countdown = useCountdown(
    isWaiting ? detail?.dueAt ?? null : null,
    isWaiting ? latestResponse?.respondedAt ?? null : null,
  );
  const waitingDisplay = isWaiting && detail ? toRequestWaitingDisplay(detail) : null;
  const completedDisplay = isCompleted && detail ? toRequestCompletedDisplay(detail) : null;

  const hasResponded = detail ? detail.responses.length > 0 : false;

  const respond = async (responseType: 'WILL_MOVE' | 'CANNOT_MOVE_NOW', estimatedMinutes: number | null) => {
    // refetch()로 다시 조회하면 그 왕복 시간만큼 카운트다운이 이미 흐른 채로 시작되니,
    // 서버가 이 응답 자체에서 돌려준 결과를 바로 반영한다.
    const result = await submit({ responseType, estimatedMinutes });
    if (result) applyResponse(result);
  };

  const statusMessage = isLoading
    ? '이동 요청 정보를 불러오는 중입니다'
    : error
      ? '이동 요청 정보를 불러오지 못했습니다'
      : !display
        ? '이동 요청 정보를 찾을 수 없습니다'
        : undefined;

  return (
    <Screen
      scroll
      edges={['top', 'right', 'left']}
      backgroundColor={isWaiting || isCompleted ? undefined : Palette.gray50}
      backgroundGradient={isCompleted ? COMPLETED_GRADIENT : isWaiting ? WAITING_GRADIENT : undefined}
    >
      <ScreenHeader
        title="이동 요청"
        style={styles.header}
        onBack={isWaiting && showDetail ? () => setShowDetail(false) : undefined}
        right={
          <RequestHeaderRight
            isWaiting={isWaiting}
            requestSource={
              display && !isCompleted
                ? { label: display.requestSourceLabel, variant: display.requestSourceVariant }
                : null
            }
          />
        }
      />

      {statusMessage || !display ? (
        <View style={styles.statusContainer}>
          <Text style={styles.statusText}>{statusMessage}</Text>
        </View>
      ) : isCompleted && completedDisplay ? (
        <RequestCompletedSection
          endTimeLabel={completedDisplay.endTimeLabel}
          timeline={completedDisplay.timeline}
          onPressHome={() => router.replace('/resident')}
        />
      ) : showWaitingView && waitingDisplay ? (
        <RequestWaitingSection
          countdownLabel={countdown.label}
          progress={countdown.progress}
          dueTimeLabel={waitingDisplay.dueTimeLabel}
          respondedTimeLabel={waitingDisplay.respondedTimeLabel}
          onPressDetail={() => setShowDetail(true)}
        />
      ) : (
        <RequestDetailSection
          photos={display.photos}
          summaryTitle={SUMMARY_TITLE}
          reasonQuote={display.reasonQuote}
          violationType={display.violationTypeLabel}
          plateNumber={display.plateNumber}
          location={display.location}
          showActions={showResponseActions}
          reminderMessage={REMINDER_MESSAGE}
          submitError={submitError}
          actionsDisabled={hasResponded || isSubmitting}
          onPressImmediate={() => respond('WILL_MOVE', 10)}
          onPress30Min={() => respond('WILL_MOVE', 30)}
          onPress60Min={() => respond('WILL_MOVE', 60)}
          onPressDecline={() => respond('CANNOT_MOVE_NOW', null)}
        />
      )}
    </Screen>
  );
}
