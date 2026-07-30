import { router, useLocalSearchParams } from 'expo-router';

import { Screen, ScreenHeader } from '@/components/ui';
import { RequestDetailBody } from '@/features/move-request/components/request-detail-body';
import { RequestHeaderRight } from '@/features/move-request/components/request-header-right';
import { useRequestDetailViewModel } from '@/features/move-request/hooks/use-request-detail-view-model';
import { Palette } from '@/styles';

import { styles } from './request-detail-screen.styles';

// 그라데이션은 화면(스크롤 영역) 전체 높이에 걸쳐 퍼지므로, 세 번째 지점에 같은 색을 한 번 더 넣어서
// 위쪽 일부(Figma 기준 42~45%)에서 색이 다 바뀌고 그 아래는 옅은 색으로 고정되게 만든다.
const WAITING_GRADIENT = ['#ede9fd', '#f7f6fb', '#f7f6fb'] as const;
const WAITING_GRADIENT_LOCATIONS = [0, 0.42, 1] as const;
const COMPLETED_GRADIENT = ['#eae7fb', '#f7f6fb', '#f7f6fb'] as const;
const COMPLETED_GRADIENT_LOCATIONS = [0, 0.45, 1] as const;
const OVERDUE_GRADIENT = ['#ffe9e2', '#f7f6fb', '#f7f6fb'] as const;
const OVERDUE_GRADIENT_LOCATIONS = [0, 0.42, 1] as const;
const REMINDER_GRADIENT = ['#fbe0dc', '#f7f6fb', '#f7f6fb'] as const;
const REMINDER_GRADIENT_LOCATIONS = [0, 0.42, 1] as const;

export default function RequestDetailScreen() {
  const { requestId: requestIdParam } = useLocalSearchParams<{ requestId?: string }>();
  const requestId = requestIdParam ? Number(requestIdParam) : null;
  const normalizedRequestId = requestId !== null && !Number.isNaN(requestId) ? requestId : null;
  const vm = useRequestDetailViewModel(normalizedRequestId);

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
      : vm.isReminderSentOverdue
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
    >
      <ScreenHeader
        title="이동 요청"
        style={styles.header}
        onBack={vm.isWaiting && vm.showDetail ? () => vm.setShowDetail(false) : undefined}
        right={
          <RequestHeaderRight
            requestSource={
              vm.display && !vm.isWaiting && !vm.isCompleted && !vm.isReminderSentOverdue
                ? { label: vm.display.requestSourceLabel, variant: vm.display.requestSourceVariant }
                : null
            }
          />
        }
      />

      <RequestDetailBody vm={vm} statusMessage={statusMessage} onPressHome={() => router.replace('/resident')} />
    </Screen>
  );
}
