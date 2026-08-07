import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { GradientScreenBackground, ResponsiveContainer, ScreenHeader, SegmentedControl, Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import { ParkingCongestionBadge } from '../components/parking-congestion-badge';
import { ParkingFloorLegend } from '../components/parking-floor-legend';
import { ParkingSpotMap } from '../components/parking-spot-map';
import { useParkingSessions } from '../hooks/use-parking-sessions';
import { useParkingZoneSummary } from '../hooks/use-parking-zone-summary';
import { toParkingStatusDisplay, type ParkingFloorKey } from '../utils/parking-zone';

import { styles } from './parking-floor-overview-screen.styles';

const FLOOR_TAB_OPTIONS: { key: ParkingFloorKey; label: string }[] = [
  { key: 'B1', label: '지하 1층' },
  { key: 'B2', label: '지하 2층' },
  { key: 'B3', label: '지하 3층' },
];

function toParkingFloorKey(floor: string | null): ParkingFloorKey | null {
  const normalized = floor?.trim().toUpperCase();
  return normalized === 'B1' || normalized === 'B2' || normalized === 'B3' ? normalized : null;
}

/** 직접 URL로 들어와 뒤로 갈 히스토리가 없을 때는 입주민 홈으로 대체 이동한다. */
function goBack() {
  if (router.canGoBack()) {
    router.back();
    return;
  }
  router.replace('/resident');
}

// J-01. 주차 도면 전체 보기
export default function ParkingFloorOverviewScreen() {
  const [activeFloor, setActiveFloor] = useState<ParkingFloorKey>('B1');
  const {
    sessions,
    isRefreshing: isSessionsRefreshing,
    refetch: refetchSessions,
  } = useParkingSessions();
  const myVehicleLocation = sessions
    .map((session) => toParkingFloorKey(session.floor))
    .find((floor): floor is ParkingFloorKey => floor !== null) ?? null;
  const myZoneNumbers = sessions.flatMap((session) =>
    session.zoneNumber ? [session.zoneNumber] : [],
  );
  const {
    summary,
    isLoading,
    isRefreshing: isSummaryRefreshing,
    error,
    refetch: refetchSummary,
  } = useParkingZoneSummary();
  const parkingStatus = summary
    ? toParkingStatusDisplay(summary, myZoneNumbers, activeFloor)
    : null;
  const mapMessage = isLoading
    ? '주차 현황을 불러오는 중입니다.'
    : error
      ? '주차 현황을 불러오지 못했습니다.'
      : !parkingStatus || parkingStatus.cells.length === 0
        ? '해당 층의 주차 현황이 없습니다.'
        : undefined;

  const handlePressMyCarLocation = () => {
    if (myVehicleLocation) setActiveFloor(myVehicleLocation);
  };

  return (
    <GradientScreenBackground
      refreshing={isSessionsRefreshing || isSummaryRefreshing}
      onRefresh={() => void Promise.all([refetchSessions(), refetchSummary()])}
    >
      <ResponsiveContainer style={styles.content}>
        <ScreenHeader
          title="주차 현황"
          style={styles.header}
          onBack={goBack}
          right={
            <Pressable
              accessibilityRole="button"
              disabled={!myVehicleLocation}
              onPress={handlePressMyCarLocation}
            >
              <Text style={[styles.headerAction, !myVehicleLocation && styles.headerActionDisabled]}>
                내 차 위치
              </Text>
            </Pressable>
          }
        />

        <Stack gap={Spacing.base + 2}>
          <SegmentedControl options={FLOOR_TAB_OPTIONS} value={activeFloor} onChange={setActiveFloor} />

          <View style={styles.mapCard}>
            {parkingStatus ? (
              <View style={styles.congestionRow}>
                <ParkingCongestionBadge
                  level={parkingStatus.congestionLevel}
                  rateLabel={parkingStatus.congestionRateLabel}
                />
              </View>
            ) : null}

            <ParkingSpotMap
              cells={parkingStatus?.cells ?? []}
              floor={activeFloor}
              message={mapMessage}
            />
            <ParkingFloorLegend />
          </View>
        </Stack>
      </ResponsiveContainer>
    </GradientScreenBackground>
  );
}
