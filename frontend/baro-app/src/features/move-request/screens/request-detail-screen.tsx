import { useLocalSearchParams } from 'expo-router';
import { Text, View } from 'react-native';

import { FormErrorBanner, Screen, ScreenHeader } from '@/components/ui';
import { RequestInfoCard } from '@/features/move-request/components/request-detail/request-info-card';
import { RequestPhoto } from '@/features/move-request/components/request-detail/request-photo';
import { RequestReminderNotice } from '@/features/move-request/components/request-detail/request-reminder-notice';
import { RequestTimeActions } from '@/features/move-request/components/request-detail/request-time-actions';
import { useMoveRequestDetail } from '@/features/move-request/hooks/use-move-request-detail';
import { useMoveRequestResponse } from '@/features/move-request/hooks/use-move-request-response';
import { toRequestDetailDisplay } from '@/features/move-request/utils/move-request';
import { Palette } from '@/styles';

import { styles } from './request-detail-screen.styles';

const SUMMARY_TITLE = '고객님의 차량 이동을\n요청드립니다';
const REMINDER_MESSAGE = '응답이 없으면 한 시간 후에 한 번 더 알려드리고,\n그 이후에는 관리사무소로 전달합니다.';

export default function RequestDetailScreen() {
  const { requestId: requestIdParam } = useLocalSearchParams<{ requestId?: string }>();
  const requestId = requestIdParam ? Number(requestIdParam) : null;
  const normalizedRequestId = requestId !== null && !Number.isNaN(requestId) ? requestId : null;
  const { detail, isLoading, error, refetch } = useMoveRequestDetail(normalizedRequestId);
  const { submit, isSubmitting, errorMessage: submitError } = useMoveRequestResponse(normalizedRequestId);
  const display = detail ? toRequestDetailDisplay(detail) : null;

  const hasResponded = detail ? detail.responses.length > 0 : false;

  const respond = async (responseType: 'WILL_MOVE' | 'CANNOT_MOVE_NOW', estimatedMinutes: number | null) => {
    const succeeded = await submit({ responseType, estimatedMinutes });
    if (succeeded) refetch();
  };

  const statusMessage = isLoading
    ? '이동 요청 정보를 불러오는 중입니다'
    : error
      ? '이동 요청 정보를 불러오지 못했습니다'
      : !display
        ? '이동 요청 정보를 찾을 수 없습니다'
        : undefined;

  return (
    <Screen scroll edges={['top', 'right', 'left']} backgroundColor={Palette.gray50}>
      <ScreenHeader
        title="이동 요청"
        style={styles.header}
        right={display ? (
          <View
            style={[
              styles.requestTypeBadge,
              display.requestSourceVariant === 'manual'
                ? styles.manualRequestBadge
                : styles.aiRequestBadge,
            ]}
          >
            <Text
              style={[
                styles.requestTypeText,
                display.requestSourceVariant === 'manual'
                  ? styles.manualRequestText
                  : styles.aiRequestText,
              ]}
            >
              {display.requestSourceLabel}
            </Text>
          </View>
        ) : null}
      />

      {statusMessage || !display ? (
        <View style={styles.statusContainer}>
          <Text style={styles.statusText}>{statusMessage}</Text>
        </View>
      ) : (
        <>
          <RequestPhoto photos={display.photos} />

          <View style={styles.mainCard}>
            <View style={styles.summary}>
              <Text style={styles.summaryTitle}>{SUMMARY_TITLE}</Text>
              <Text style={styles.summaryReason}>{display.reasonQuote}</Text>
            </View>

            <RequestInfoCard
              violationType={display.violationTypeLabel}
              plateNumber={display.plateNumber}
              location={display.location}
            />

            <RequestReminderNotice message={REMINDER_MESSAGE} />

            {submitError ? <FormErrorBanner message={submitError} /> : null}

            <RequestTimeActions
              disabled={hasResponded || isSubmitting}
              onPressImmediate={() => respond('WILL_MOVE', 10)}
              onPress30Min={() => respond('WILL_MOVE', 30)}
              onPress60Min={() => respond('WILL_MOVE', 60)}
              onPressDecline={() => respond('CANNOT_MOVE_NOW', null)}
            />
          </View>
        </>
      )}
    </Screen>
  );
}
