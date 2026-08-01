import { router } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { GradientScreenBackground, ResponsiveContainer, ScreenHeader, SegmentedControl, Stack } from '@/components/ui';
import { useMoveRequests } from '@/features/move-request/hooks/use-move-requests';
import { toRequestListItemDisplay } from '@/features/move-request/utils/move-request';
import { Spacing } from '@/styles';

import { RequestListCard } from '../components/requests-list/request-list-card';
import { styles } from './requests-screen.styles';

export type RequestsScope = 'SENT' | 'RECEIVED';

export default function RequestsScreen() {
  const [scope, setScope] = useState<RequestsScope>('SENT');
  const sentQuery = useMoveRequests('SENT');
  const receivedQuery = useMoveRequests('RECEIVED');
  const currentQuery = scope === 'SENT' ? sentQuery : receivedQuery;
  const items = currentQuery.moveRequests.map(toRequestListItemDisplay);

  const scopeOptions: { key: RequestsScope; label: string }[] = [
    { key: 'SENT', label: `보낸 요청 ${sentQuery.moveRequests.length}` },
    { key: 'RECEIVED', label: `받은 요청 ${receivedQuery.moveRequests.length}` },
  ];

  const statusMessage = currentQuery.isLoading
    ? '이동 요청을 불러오는 중입니다'
    : currentQuery.error
      ? '이동 요청을 불러오지 못했습니다'
      : items.length === 0
        ? scope === 'SENT'
          ? '보낸 이동 요청이 없습니다'
          : '받은 이동 요청이 없습니다'
        : undefined;

  const handlePressItem = (requestId: number) => {
    router.push({ pathname: '/resident/request-detail', params: { requestId: String(requestId) } });
  };

  return (
    <GradientScreenBackground contentContainerStyle={styles.content}>
      <ResponsiveContainer style={styles.container}>
        <ScreenHeader title="요청" showBackButton={false} />

        <Stack gap={Spacing.md}>
          <SegmentedControl options={scopeOptions} value={scope} onChange={setScope} />

          {statusMessage ? (
            <View style={styles.emptyContainer}>
              <Text style={styles.emptyText}>{statusMessage}</Text>
            </View>
          ) : (
            <Stack gap={Spacing.base}>
              {items.map((item) => (
                <RequestListCard
                  key={item.requestId}
                  item={item}
                  // 받은 요청은 실제 requestId를 사용해 상세 조회 API 화면으로 이동한다.
                  onPress={scope === 'RECEIVED' ? () => handlePressItem(item.requestId) : undefined}
                />
              ))}
            </Stack>
          )}
        </Stack>
      </ResponsiveContainer>
    </GradientScreenBackground>
  );
}
