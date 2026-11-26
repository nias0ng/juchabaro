import { router } from 'expo-router';
import { useState } from 'react';

import { AsyncStateView, GradientScreenBackground, ResponsiveContainer, ScreenHeader, Stack } from '@/components/ui';
import { RequestHistoryCard } from '@/features/move-request/components/history/request-history-card';
import { useMoveRequests } from '@/features/move-request/hooks/use-move-requests';
import { toRequestSummaryDisplay } from '@/features/move-request/utils/move-request';
import { useAuth } from '@/providers/auth-provider';
import { Spacing } from '@/styles';
import { withAdaptiveColors } from '@/hooks/adaptive-color-scope';

import { styles } from './request-history-screen.styles';

function RequestHistoryScreen() {
  const { user } = useAuth();
  const [isPullRefreshing, setIsPullRefreshing] = useState(false);
  const { moveRequests, isLoading, error, refetch } = useMoveRequests('ALL');

  const handleRefresh = async () => {
    setIsPullRefreshing(true);
    try {
      await refetch();
    } finally {
      setIsPullRefreshing(false);
    }
  };

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
      refreshing={isPullRefreshing}
      onRefresh={() => void handleRefresh()}
    >
      <ResponsiveContainer>
        <ScreenHeader title="요청 내역" style={styles.header} />

        <AsyncStateView message={statusMessage} fill={false}>
          <Stack gap={Spacing.base} style={styles.content}>
            {moveRequests.map((summary) => (
              <RequestHistoryCard
                key={summary.requestId}
                display={toRequestSummaryDisplay(summary)}
                status={summary.requestStatus}
                onPress={() =>
                  router.push({
                    pathname: '/resident/request-detail',
                    params: {
                      requestId: String(summary.requestId),
                      viewMode: summary.requesterUserId === user?.userId ? 'requester' : 'recipient',
                    },
                  })
                }
              />
            ))}
          </Stack>
        </AsyncStateView>
      </ResponsiveContainer>
    </GradientScreenBackground>
  );
}

export default withAdaptiveColors(RequestHistoryScreen);
