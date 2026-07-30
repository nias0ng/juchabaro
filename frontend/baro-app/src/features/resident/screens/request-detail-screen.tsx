import { useLocalSearchParams } from 'expo-router';
import { Text, View } from 'react-native';

import { Screen, ScreenHeader } from '@/components/ui';
import { RequestInfoCard } from '@/features/resident/components/request-detail/request-info-card';
import { RequestPhoto } from '@/features/resident/components/request-detail/request-photo';
import { RequestReminderNotice } from '@/features/resident/components/request-detail/request-reminder-notice';
import { RequestTimeActions } from '@/features/resident/components/request-detail/request-time-actions';
import { useMoveRequestDetail } from '@/features/resident/hooks/use-move-request-detail';
import { toRequestDetailDisplay } from '@/features/resident/utils/move-request';
import { Palette } from '@/styles';

import { styles } from './request-detail-screen.styles';

const SUMMARY_TITLE = '고객님의 차량 이동을\n요청드립니다';
const REMINDER_MESSAGE = '응답이 없으면 한 시간 후에 한 번 더 알려드리고,\n그 이후에는 관리사무소로 전달합니다.';

export default function RequestDetailScreen() {
  const { requestId: requestIdParam } = useLocalSearchParams<{ requestId?: string }>();
  const requestId = requestIdParam ? Number(requestIdParam) : null;
  const { detail, isLoading, error } = useMoveRequestDetail(
    requestId !== null && !Number.isNaN(requestId) ? requestId : null,
  );
  const display = detail ? toRequestDetailDisplay(detail) : null;

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
        right={
          <View style={styles.urgentBadge}>
            <Text style={styles.urgentText}>긴급</Text>
          </View>
        }
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

            <RequestTimeActions />
          </View>
        </>
      )}
    </Screen>
  );
}
