import { router } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { GradientScreenBackground, ResponsiveContainer, ScreenHeader, Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import { RequestListCard, type RequestListItemDisplay } from '../components/requests-list/request-list-card';
import { RequestsTabSelector, type RequestsScope } from '../components/requests-list/requests-tab-selector';
import { styles } from './requests-screen.styles';

// TODO(requests-screen): GET /move-requests?scope=&requestStatus= 연동 전까지 Figma 예시값을 그대로 쓴다.
const MOCK_SENT_REQUESTS: RequestListItemDisplay[] = [
  {
    requestId: 201,
    status: 'RESPONDED',
    timestampLabel: '오늘 15:00',
    plateNumber: '12가 ****',
    situationLabel: '이중 주차 · B-14',
    countdownLabel: '18:42 남음',
  },
  {
    requestId: 202,
    status: 'PENDING',
    timestampLabel: '오늘 11:07',
    plateNumber: '78다 ****',
    situationLabel: '통로 점유 · A-03',
  },
  {
    requestId: 998,
    status: 'CLOSED',
    timestampLabel: '어제 21:14',
    plateNumber: '45마 ****',
    situationLabel: '주차선 침범 · D-21',
    closedSummary: '8분 만에 이동 완료',
  },
];

const MOCK_RECEIVED_REQUESTS: RequestListItemDisplay[] = [
  {
    requestId: 995,
    status: 'PENDING',
    timestampLabel: '오늘 09:20',
    plateNumber: '12가 3456',
    situationLabel: '이중 주차 · B-14',
  },
];

export default function RequestsScreen() {
  const [scope, setScope] = useState<RequestsScope>('SENT');
  const items = scope === 'SENT' ? MOCK_SENT_REQUESTS : MOCK_RECEIVED_REQUESTS;

  const handlePressItem = (requestId: number) => {
    router.push({ pathname: '/resident/request-detail', params: { requestId: String(requestId) } });
  };

  return (
    <GradientScreenBackground contentContainerStyle={styles.content}>
      <ResponsiveContainer style={styles.container}>
        <ScreenHeader title="요청" showBackButton={false} />

        <Stack gap={Spacing.md}>
          <RequestsTabSelector
            value={scope}
            onChange={setScope}
            sentCount={MOCK_SENT_REQUESTS.length}
            receivedCount={MOCK_RECEIVED_REQUESTS.length}
          />

          {items.length > 0 ? (
            <Stack gap={Spacing.base}>
              {items.map((item) => (
                <RequestListCard
                  key={item.requestId}
                  item={item}
                  // 보낸 요청은 아직 상세 화면이 없어서 눌러도 이동하지 않는다. 받은 요청만 request-detail로 연결한다.
                  onPress={scope === 'RECEIVED' ? () => handlePressItem(item.requestId) : undefined}
                />
              ))}
            </Stack>
          ) : (
            <View style={styles.emptyContainer}>
              <Text style={styles.emptyText}>표시할 요청이 없습니다</Text>
            </View>
          )}
        </Stack>
      </ResponsiveContainer>
    </GradientScreenBackground>
  );
}
