import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { Screen, ScreenHeader } from '@/components/ui';
import { RequestDetailBody } from '@/features/move-request/components/request-detail-body';
import { RequestHeaderRight } from '@/features/move-request/components/request-header-right';
import { useRequestDetailViewModel } from '@/features/move-request/hooks/use-request-detail-view-model';
import { Palette } from '@/styles';

import { styles } from './request-detail-screen.styles';

const WAITING_GRADIENT = ['#ede9fd', '#f7f6fb', '#f7f6fb'] as const;
const WAITING_GRADIENT_LOCATIONS = [0, 0.42, 1] as const;
const COMPLETED_GRADIENT = ['#eae7fb', '#f7f6fb', '#f7f6fb'] as const;
const COMPLETED_GRADIENT_LOCATIONS = [0, 0.45, 1] as const;
const OVERDUE_GRADIENT = ['#ffe9e2', '#f7f6fb', '#f7f6fb'] as const;
const OVERDUE_GRADIENT_LOCATIONS = [0, 0.42, 1] as const;
const REMINDER_GRADIENT = ['#fbe0dc', '#f7f6fb', '#f7f6fb'] as const;
const REMINDER_GRADIENT_LOCATIONS = [0, 0.42, 1] as const;

/** 이동 요청 상태(대기/미이동/이관/완료 등)에 따라 다른 레이아웃을 그리는 상세 화면. 분기는 useRequestDetailViewModel이 계산한다. */
export default function RequestDetailScreen() {
  const { requestId: requestIdParam, viewMode: viewModeParam } = useLocalSearchParams<{
    requestId?: string;
    viewMode?: string;
  }>();
  const requestId = requestIdParam ? Number(requestIdParam) : null;
  const normalizedRequestId = requestId !== null && !Number.isNaN(requestId) ? requestId : null;
  const viewMode = viewModeParam === 'requester' ? 'requester' : 'recipient';
  const vm = useRequestDetailViewModel(normalizedRequestId, viewMode);
  const [isPullRefreshing, setIsPullRefreshing] = useState(false);

  const handleRefresh = async () => {
    setIsPullRefreshing(true);
    try {
      await vm.refetch();
    } finally {
      setIsPullRefreshing(false);
    }
  };

  const statusMessage = vm.isLoading
    ? '이동 요청 정보를 불러오는 중입니다'
    : vm.error
      ? '이동 요청 정보를 불러오지 못했습니다'
      : !vm.display
        ? '이동 요청 정보를 찾을 수 없습니다'
        : undefined;

  const background = vm.isCompleted
    ? { gradient: COMPLETED_GRADIENT, locations: COMPLETED_GRADIENT_LOCATIONS }
    : vm.isOverdueWaiting
      ? { gradient: OVERDUE_GRADIENT, locations: OVERDUE_GRADIENT_LOCATIONS }
      : vm.showEscalationView
        ? { gradient: REMINDER_GRADIENT, locations: REMINDER_GRADIENT_LOCATIONS }
        : vm.isWaiting
          ? { gradient: WAITING_GRADIENT, locations: WAITING_GRADIENT_LOCATIONS }
          : null;

  return (
    <Screen
      scroll
      edges={['top', 'right', 'left']}
      backgroundColor={background ? undefined : Palette.gray50}
      backgroundGradient={background?.gradient}
      backgroundGradientLocations={background?.locations}
      refreshing={isPullRefreshing}
      onRefresh={() => void handleRefresh()}
    >
      <View style={styles.content}>
        <ScreenHeader
          title="이동 요청"
          style={styles.header}
          onBack={vm.isWaiting && vm.showDetail ? () => vm.setShowDetail(false) : undefined}
          right={
            <RequestHeaderRight
              requestSource={
                vm.display && !vm.isWaiting && !vm.isCompleted && !vm.showEscalationView
                  ? { label: vm.display.requestSourceLabel, variant: vm.display.requestSourceVariant }
                  : null
              }
            />
          }
        />

        <RequestDetailBody vm={vm} statusMessage={statusMessage} onPressHome={() => router.replace('/resident')} />
      </View>
    </Screen>
  );
}
