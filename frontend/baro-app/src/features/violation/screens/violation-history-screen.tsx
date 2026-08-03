import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { Text, View } from 'react-native';

import { GradientScreenBackground, ResponsiveContainer, ScreenHeader, SegmentedControl, Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import { ViolationListItem } from '../components/violation-list-item';
import { ViolationSummaryCard } from '../components/violation-summary-card';
import { MOCK_VIOLATION_HISTORY, MOCK_VIOLATION_SUMMARY, type MockViolationItem } from '../mocks/violation-history.mock';

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

function filterByStatus(items: MockViolationItem[], filter: ViolationFilter): MockViolationItem[] {
  if (filter === 'ALL') return items;
  return items.filter((item) => item.status === filter);
}

// 이미 월 내림차순으로 정렬된 배열을 연속된 monthLabel 기준으로 묶는다.
function groupByMonth(items: MockViolationItem[]): { monthLabel: string; items: MockViolationItem[] }[] {
  const groups: { monthLabel: string; items: MockViolationItem[] }[] = [];

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

  const monthGroups = useMemo(
    () => groupByMonth(filterByStatus(MOCK_VIOLATION_HISTORY, filter)),
    [filter],
  );

  return (
    <GradientScreenBackground>
      <ScreenHeader title="위반 이력" style={styles.header} onBack={goBack} />

      <ResponsiveContainer style={styles.content}>
        <Stack gap={Spacing.base + 2}>
          {/* TODO: 위반 이력 조회 API 완성 후 실제 서버 응답의 최근 90일 통계로 교체 */}
          <ViolationSummaryCard summary={MOCK_VIOLATION_SUMMARY} />

          <SegmentedControl options={FILTER_OPTIONS} value={filter} onChange={setFilter} />

          <View style={styles.listCard}>
            {/* TODO: 위반 이력 조회 API 완성 후 mock 데이터를 서버 응답(월별 그룹 포함)으로 교체 */}
            {monthGroups.length === 0 ? (
              <Text style={styles.emptyText}>표시할 위반 이력이 없습니다.</Text>
            ) : (
              monthGroups.map((group) => (
                <View key={group.monthLabel} style={styles.monthGroup}>
                  <Text style={styles.monthLabel}>{group.monthLabel}</Text>
                  <View style={styles.monthItems}>
                    {group.items.map((item) => (
                      <ViolationListItem key={item.id} item={item} />
                    ))}
                  </View>
                </View>
              ))
            )}
          </View>
        </Stack>
      </ResponsiveContainer>
    </GradientScreenBackground>
  );
}
