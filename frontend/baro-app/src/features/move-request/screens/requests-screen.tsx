import { router } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { GradientScreenBackground, ResponsiveContainer, ScreenHeader, Stack } from '@/components/ui';
import type { MoveRequestStatus, MoveRequestSummary } from '@/features/move-request/api/types';
import { useMoveRequests } from '@/features/move-request/hooks/use-move-requests';
import { toRequestSummaryDisplay } from '@/features/move-request/utils/move-request';
import { Spacing } from '@/styles';

import {
  RequestListCard,
  type RequestListItemDisplay,
  type RequestListStatus,
} from '../components/requests-list/request-list-card';
import { RequestsTabSelector, type RequestsScope } from '../components/requests-list/requests-tab-selector';
import { styles } from './requests-screen.styles';

const LIST_STATUS: Record<MoveRequestStatus, RequestListStatus> = {
  SENT: 'PENDING',
  RESPONDED: 'RESPONDED',
  REMINDER_SENT: 'PENDING',
  COMPLETED: 'CLOSED',
  NEED_ADMIN: 'CLOSED',
  CANCELLED: 'CLOSED',
};

function toRequestListItem(summary: MoveRequestSummary): RequestListItemDisplay {
  const display = toRequestSummaryDisplay(summary);
  const status = LIST_STATUS[summary.requestStatus];

  return {
    requestId: display.requestId,
    status,
    timestampLabel: display.requestedAtLabel,
    plateNumber: display.plateNumber,
    situationLabel: display.eventTypeLabel,
    closedSummary: status === 'CLOSED' ? display.statusLabel : undefined,
  };
}

export default function RequestsScreen() {
  const [scope, setScope] = useState<RequestsScope>('SENT');
  const sentQuery = useMoveRequests('SENT');
  const receivedQuery = useMoveRequests('RECEIVED');
  const currentQuery = scope === 'SENT' ? sentQuery : receivedQuery;
  const items = currentQuery.moveRequests.map(toRequestListItem);

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
          <RequestsTabSelector
            value={scope}
            onChange={setScope}
            sentCount={sentQuery.moveRequests.length}
            receivedCount={receivedQuery.moveRequests.length}
          />

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
