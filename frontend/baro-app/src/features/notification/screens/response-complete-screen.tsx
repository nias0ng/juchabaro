import { LinearGradient } from 'expo-linear-gradient';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect } from 'react';
import { Text, View } from 'react-native';

import { Screen } from '@/components/ui';
import { useMoveRequestDetail } from '@/features/move-request/hooks/use-move-request-detail';
import { ResponseSummaryCard } from '@/features/notification/components/response-complete/response-summary-card';
import { RedirectCountdown } from '@/features/notification/components/response-complete/redirect-countdown';
import { useRedirectCountdown } from '@/features/notification/hooks/use-redirect-countdown';
import { formatEstimatedMinutesLabel, formatTimeLabel } from '@/features/notification/utils/notification';
import { Gradients } from '@/styles';

import { styles } from './response-complete-screen.styles';

const DEFAULT_LOCATION_LABEL = '위치 정보 없음';

export default function ResponseCompleteScreen() {
  const { requestId: requestIdParam } = useLocalSearchParams<{ requestId?: string }>();
  const requestId = requestIdParam ? Number(requestIdParam) : null;
  const normalizedRequestId = requestId !== null && !Number.isNaN(requestId) ? requestId : null;

  const { detail, isLoading, error } = useMoveRequestDetail(normalizedRequestId);
  const secondsLeft = useRedirectCountdown();
  const latestResponse = detail && detail.responses.length > 0 ? detail.responses[detail.responses.length - 1] : null;

  useEffect(() => {
    if (secondsLeft > 0 || normalizedRequestId === null) return;
    // E-12(이동 예정/약속 대기)는 별도 화면이 아니라 request-detail-screen이 requestStatus=RESPONDED일 때
    // 그 자리에서 그려주는 뷰라서, 카운트다운이 끝나면 그 라우트로 되돌아가면 된다.
    router.replace({
      pathname: '/resident/request-detail',
      params: { requestId: String(normalizedRequestId) },
    });
  }, [secondsLeft, normalizedRequestId]);

  const statusMessage = isLoading
    ? '응답 정보를 불러오는 중입니다'
    : error || !detail || !latestResponse
      ? '응답 정보를 찾을 수 없습니다'
      : undefined;

  return (
    <Screen
      edges={['top', 'right', 'left']}
      backgroundGradient={Gradients.responseComplete}
      backgroundGradientLocations={[0, 0.55, 1]}
      contentContainerStyle={styles.content}
    >
      {statusMessage || !detail || !latestResponse ? (
        <View style={styles.statusContainer}>
          <Text style={styles.statusText}>{statusMessage}</Text>
        </View>
      ) : (
        <>
          <View style={styles.iconOuter}>
            <LinearGradient colors={Gradients.avatar} style={styles.iconInner} />
          </View>

          <Text style={styles.title}>응답이 전달되었습니다</Text>
          <Text style={styles.subtitle}>
            {formatTimeLabel(detail.dueAt)}까지 이동해 주세요.{'\n'}이동이 확인되면 요청이 자동 종료됩니다.
          </Text>

          <View style={styles.summaryMargin}>
            <ResponseSummaryCard
              responseLabel={formatEstimatedMinutesLabel(latestResponse.estimatedMinutes)}
              vehicleLabel={`${detail.targetVehicle.plateNumber} · ${detail.event.zoneNumber ?? DEFAULT_LOCATION_LABEL}`}
              dueAtLabel={formatTimeLabel(detail.dueAt)}
              deliveredAtLabel={formatTimeLabel(latestResponse.respondedAt)}
            />
          </View>

          <View style={styles.noticeBox}>
            <Text style={styles.noticeText}>
              기한까지 이동이 확인되지 않으면 재안내 후,{'\n'}반복 시 관리사무소에 위반 이력이 전달됩니다.
            </Text>
          </View>

          <View style={styles.countdownMargin}>
            <RedirectCountdown secondsLeft={secondsLeft} />
          </View>
        </>
      )}
    </Screen>
  );
}
