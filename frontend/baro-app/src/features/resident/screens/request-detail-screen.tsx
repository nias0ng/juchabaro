import { Text, View } from 'react-native';

import { Screen, ScreenHeader } from '@/components/ui';
import { RequestInfoCard } from '@/features/resident/components/request-detail/request-info-card';
import { RequestPhoto } from '@/features/resident/components/request-detail/request-photo';
import { RequestReminderNotice } from '@/features/resident/components/request-detail/request-reminder-notice';
import { RequestTimeActions } from '@/features/resident/components/request-detail/request-time-actions';
import { Palette } from '@/styles';

import { styles } from './request-detail-screen.styles';

// TODO(request-detail): GET /api/move-requests/{requestId} 연동 전까지 Figma E-11 기준 값으로 고정.
const MOCK_REQUEST = {
  title: '고객님의 차량 이동을\n요청드립니다',
  reason: '"출차 통로를 막고 있어 차량 이동을 요청했습니다."',
  violationType: '이중 주차',
  plateNumber: '12가 3456',
  location: 'B1 · B-14',
  photoIndex: 1,
  photoTotal: 2,
  reminderMessage: '응답이 없으면 15:00에 한 번 더 알려드리고,\n그 이후에는 관리사무소로 전달합니다.',
};

export default function RequestDetailScreen() {
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

      <RequestPhoto photoIndex={MOCK_REQUEST.photoIndex} photoTotal={MOCK_REQUEST.photoTotal} />

      <View style={styles.mainCard}>
        <View style={styles.summary}>
          <Text style={styles.summaryTitle}>{MOCK_REQUEST.title}</Text>
          <Text style={styles.summaryReason}>{MOCK_REQUEST.reason}</Text>
        </View>

        <RequestInfoCard
          violationType={MOCK_REQUEST.violationType}
          plateNumber={MOCK_REQUEST.plateNumber}
          location={MOCK_REQUEST.location}
        />

        <RequestReminderNotice message={MOCK_REQUEST.reminderMessage} />

        <RequestTimeActions />
      </View>
    </Screen>
  );
}
