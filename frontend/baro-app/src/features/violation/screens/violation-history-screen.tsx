import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { Text, View } from 'react-native';

import {
  AsyncStateView,
  GradientScreenBackground,
  ResponsiveContainer,
  ScreenHeader,
  SegmentedControl,
  Stack,
} from '@/components/ui';
import { Spacing } from '@/styles';

import { ViolationListItem } from '../components/violation-list-item';
import { ViolationSummaryCard } from '../components/violation-summary-card';
import type { ViolationHistoryItem } from '../api/types';
import { useViolationHistory } from '../hooks/use-violation-history';
import { useViolationStats } from '../hooks/use-violation-stats';

import { styles } from './violation-history-screen.styles';

export type ViolationFilter = 'ALL' | 'UNRESOLVED' | 'RESOLVED';

const FILTER_OPTIONS: { key: ViolationFilter; label: string }[] = [
  { key: 'ALL', label: '전체' },
  { key: 'UNRESOLVED', label: '미해결' },
  { key: 'RESOLVED', label: '해결' },
];

/** 직접 URL로 들어와 뒤로 갈 히스토리가 없을 때는 입주민 홈으로 대체 이동한다. */
function goBack() {
  if (router.canGoBack()) {
    router.back();
    return;
  }
  router.replace('/resident');
}

function filterByStatus(items: ViolationHistoryItem[], filter: ViolationFilter): ViolationHistoryItem[] {
  if (filter === 'ALL') return items;
  return items.filter((item) => item.status === filter);
}

// 이미 월 내림차순으로 정렬된 배열을 연속된 monthLabel 기준으로 묶는다.
function groupByMonth(items: ViolationHistoryItem[]): { monthLabel: string; items: ViolationHistoryItem[] }[] {
  const groups: { monthLabel: string; items: ViolationHistoryItem[] }[] = [];

  for (const item of items) {
    const lastGroup = groups[groups.length - 1];
    if (lastGroup && lastGroup.monthLabel === item.monthLabel) {
      lastGroup.items.push(item);
    } else {
      groups.push({ monthLabel: item.monthLabel, items: [item] });
    }
  }

  return groups;
}

// J-02. 위반 이력 전체
export default function ViolationHistoryScreen() {
  const [filter, setFilter] = useState<ViolationFilter>('ALL');
  const {
    stats,
    isLoading: isStatsLoading,
    isRefreshing: isStatsRefreshing,
    error: statsError,
    refetch: refetchStats,
  } = useViolationStats();
  const {
    violations,
    isLoading: isHistoryLoading,
    isRefreshing: isHistoryRefreshing,
    error: historyError,
    refetch: refetchHistory,
  } = useViolationHistory();

  const monthGroups = useMemo(
    () => groupByMonth(filterByStatus(violations, filter)),
    [filter, violations],
  );

  const historyStatusMessage = isHistoryLoading
    ? '위반 이력을 불러오는 중입니다.'
    : historyError
      ? '위반 이력을 불러오지 못했습니다.'
      : monthGroups.length === 0
        ? '표시할 위반 이력이 없습니다.'
        : undefined;

  return (
    <GradientScreenBackground
      refreshing={isStatsRefreshing || isHistoryRefreshing}
      onRefresh={() => void Promise.all([refetchStats(), refetchHistory()])}
    >
      <ResponsiveContainer style={styles.content}>
        <ScreenHeader title="위반 이력" style={styles.header} onBack={goBack} />

        <Stack gap={Spacing.base + 2}>
          <AsyncStateView
            message={
              isStatsLoading
                ? '위반 통계를 불러오는 중입니다.'
                : statsError
                  ? '위반 통계를 불러오지 못했습니다.'
                  : undefined
            }
            fill={false}
          >
            {stats ? <ViolationSummaryCard summary={stats} /> : null}
          </AsyncStateView>

          <SegmentedControl options={FILTER_OPTIONS} value={filter} onChange={setFilter} />

          <View style={styles.listCard}>
            <AsyncStateView message={historyStatusMessage} fill={false}>
              {monthGroups.map((group) => (
                <View key={group.monthLabel} style={styles.monthGroup}>
                  <Text style={styles.monthLabel}>{group.monthLabel}</Text>
                  <View style={styles.monthItems}>
                    {group.items.map((item, index) => (
                      <View key={item.requestId} style={styles.historyItem}>
                        <ViolationListItem
                          item={item}
                          onPress={() =>
                            router.push({
                              pathname: '/resident/request-detail',
                              params: {
                                requestId: String(item.requestId),
                                viewMode: 'recipient',
                              },
                            })
                          }
                        />
                        {index < group.items.length - 1 ? <View style={styles.itemDivider} /> : null}
                      </View>
                    ))}
                  </View>
                </View>
              ))}
            </AsyncStateView>
          </View>
        </Stack>
      </ResponsiveContainer>
    </GradientScreenBackground>
  );
}
