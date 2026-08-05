import { router } from 'expo-router';

import { AsyncStateView, GradientScreenBackground, ScreenHeader, Stack } from '@/components/ui';
import { RequestHistoryCard } from '@/features/move-request/components/history/request-history-card';
import { useMoveRequests } from '@/features/move-request/hooks/use-move-requests';
import { toRequestSummaryDisplay } from '@/features/move-request/utils/move-request';
import { Spacing } from '@/styles';

import { styles } from './request-history-screen.styles';

export default function RequestHistoryScreen() {
  const { moveRequests, isLoading, isRefreshing, error, refetch } = useMoveRequests('ALL');

  const statusMessage = isLoading
    ? '요청 내역을 불러오는 중입니다'
    : error
      ? '요청 내역을 불러오지 못했습니다'
      : moveRequests.length === 0
        ? '받은 이동 요청이 없습니다'
        : undefined;

  return (
    <GradientScreenBackground
      edges={['top', 'right', 'left']}
      refreshing={isRefreshing}
      onRefresh={() => void refetch()}
    >
      <ScreenHeader title="요청 내역" style={styles.header} />

      <AsyncStateView message={statusMessage} fill={false} style={styles.statusContainer}>
        <Stack gap={Spacing.base} style={styles.content}>
          {moveRequests.map((summary) => (
            <RequestHistoryCard
              key={summary.requestId}
              display={toRequestSummaryDisplay(summary)}
              status={summary.requestStatus}
              onPress={() =>
                router.push({
                  pathname: '/resident/request-detail',
                  params: { requestId: String(summary.requestId) },
                })
              }
            />
          ))}
        </Stack>
      </AsyncStateView>
    </GradientScreenBackground>
  );
}
