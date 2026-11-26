import { Redirect } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { AsyncStateView } from '@/components/ui/async-state-view';
import { BottomNavBar } from '@/components/ui/bottom-nav-bar';
import { FormSectionLabel } from '@/components/ui/form-section-label';
import { GradientScreenBackground } from '@/components/ui/gradient-screen-background';
import { InfoRowCard } from '@/components/ui/info-row-card';
import { ScreenHeader } from '@/components/ui/screen-header';
import { SegmentedControl } from '@/components/ui/segmented-control';
import { RequestStatCardRow } from '@/features/move-request/components/request-stat-card-row';
import { RequestTimelineCard } from '@/features/move-request/components/request-timeline-card';
import { RequestProgressCard } from '@/features/move-request/components/request-waiting/request-progress-card';
import { RequestListCard } from '@/features/move-request/components/requests-list/request-list-card';
import { RequestStatusBadge } from '@/features/move-request/components/requests-list/request-status-badge';
import { useColorTokens } from '@/hooks/use-color-tokens';
import { useThemedStyles } from '@/hooks/use-themed-styles';

import {
  LIST_ITEM_CLOSED,
  LIST_ITEM_PENDING,
  STATUS_FIXTURES,
  TIMELINE_DEFAULT,
  TIMELINE_OVERDUE,
  TIMELINE_REMINDER,
} from '../fixtures/move-request-fixtures';
import { createStyles } from './design-system-screen.styles';

type Swatch = { name: string; value: string };
type TabKey = 'received' | 'sent';

function flattenTokens(value: unknown, prefix: string): Swatch[] {
  if (typeof value === 'string') return [{ name: prefix, value }];
  if (Array.isArray(value)) return value.map((item, index) => ({ name: `${prefix}[${index}]`, value: String(item) }));
  if (typeof value !== 'object' || value === null) return [];
  return Object.entries(value).flatMap(([key, child]) => flattenTokens(child, `${prefix}.${key}`));
}

const TABS: { key: TabKey; label: string }[] = [
  { key: 'received', label: '받은 요청' },
  { key: 'sent', label: '보낸 요청' },
];

/**
 * 개발 전용 미리보기. 서버 없이 토큰과 컴포넌트를 라이트/다크로 확인하기 위한 화면이다.
 * 웹 배포가 src/app의 모든 라우트를 내보내므로 배포 빌드에서는 홈으로 돌려보낸다.
 */
export default function DesignSystemScreen() {
  const tokens = useColorTokens();
  const styles = useThemedStyles(createStyles);
  const [tab, setTab] = useState<TabKey>('received');
  const [navKey, setNavKey] = useState('request');

  if (!__DEV__) return <Redirect href="/" />;

  return (
    <GradientScreenBackground contentContainerStyle={styles.content}>
      <ScreenHeader title="디자인 시스템" showBackButton={false} />

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>색상 토큰</Text>
        {Object.entries(tokens).map(([group, value]) => (
          <View key={group} style={styles.section}>
            <Text style={styles.groupTitle}>{group}</Text>
            <View style={styles.swatchGrid}>
              {flattenTokens(value, group).map((swatch) => (
                <View key={swatch.name} style={styles.swatch}>
                  <View style={[styles.chip, { backgroundColor: swatch.value }]} />
                  <View style={styles.swatchText}>
                    <Text style={styles.swatchName}>{swatch.name}</Text>
                    <Text style={styles.swatchValue}>{swatch.value}</Text>
                  </View>
                </View>
              ))}
            </View>
          </View>
        ))}
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>공용 컴포넌트</Text>
        <SegmentedControl options={TABS} value={tab} onChange={setTab} />
        <FormSectionLabel label="주차 위치" suffix="(선택)" />
        <FormSectionLabel label="요청 사유" suffix="최대 100자" variant="muted" />
        <InfoRowCard
          rows={[
            { label: '차량 번호', value: '12가 3456' },
            { label: '이동 예정', value: '오후 2:50' },
          ]}
          statusRow={{ label: '요청자에게 전달 완료', time: '14:32' }}
        />
        <AsyncStateView message="받은 요청이 없어요." fill={false}>
          {null}
        </AsyncStateView>
        <BottomNavBar
          items={[
            { key: 'home', label: '홈', icon: 'home' },
            { key: 'request', label: '요청', icon: 'request', badge: true },
            { key: 'parking', label: '주차 현황', icon: 'parking' },
            { key: 'user', label: '내 정보', icon: 'user' },
          ]}
          activeKey={navKey}
          onPressItem={setNavKey}
        />
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>이동 요청</Text>
        <View style={styles.row}>
          {STATUS_FIXTURES.map((status) => (
            <RequestStatusBadge key={status} status={status} />
          ))}
        </View>
        <RequestListCard item={LIST_ITEM_PENDING} />
        <RequestListCard item={LIST_ITEM_CLOSED} />
        <RequestStatCardRow leftLabel="요청 시각" leftValue="14:30" rightLabel="경과 시간" rightValue="25분" />
        <RequestProgressCard dueTimeLabel="14:50" respondedTimeLabel="오후 2:32" />
        <RequestTimelineCard title="진행 내역" timeline={TIMELINE_DEFAULT} />
        <RequestTimelineCard
          header={{ label: '재알림', value: '1회 발송' }}
          timeline={TIMELINE_REMINDER}
          pendingStep={{ label: '관리사무소 이관', status: '45분 후' }}
        />
        <RequestTimelineCard title="기한 초과" timeline={TIMELINE_OVERDUE} />
      </View>
    </GradientScreenBackground>
  );
}
