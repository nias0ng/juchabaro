import { router } from 'expo-router';
import { useRef, useState } from 'react';
import {
  Pressable,
  ScrollView,
  Text,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native';

import { GradientScreenBackground, ResponsiveContainer, ScreenHeader, SegmentedControl, Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import { ParkingAvailabilityLabel } from '../components/parking-availability-label';
import { ParkingCongestionBadge } from '../components/parking-congestion-badge';
import { ParkingFloorLegend } from '../components/parking-floor-legend';
import { ParkingSpotMap } from '../components/parking-spot-map';
import { useParkingSessions } from '../hooks/use-parking-sessions';
import { useParkingZoneSummary } from '../hooks/use-parking-zone-summary';
import {
  PARKING_FLOORS,
  toParkingStatusDisplay,
  type ParkingFloorKey,
  type ParkingStatusDisplay,
} from '../utils/parking-zone';

import { styles } from './parking-floor-overview-screen.styles';

const FLOOR_TAB_OPTIONS: { key: ParkingFloorKey; label: string }[] = [
  { key: 'B1', label: 'B1' },
  { key: 'B2', label: 'B2' },
  { key: 'B3', label: 'B3' },
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

type ParkingFloorPageProps = {
  floor: ParkingFloorKey;
  status: ParkingStatusDisplay | null;
  isLoading: boolean;
  hasError: boolean;
  width?: number;
};

function ParkingFloorPage({
  floor,
  status,
  isLoading,
  hasError,
  width,
}: ParkingFloorPageProps) {
  const mapMessage = isLoading
    ? '주차 현황을 불러오는 중입니다.'
    : hasError
      ? '주차 현황을 불러오지 못했습니다.'
      : !status || status.cells.length === 0
        ? '해당 층의 주차 현황이 없습니다.'
        : undefined;

  return (
    <View style={[styles.floorPage, width ? { width } : null]}>
      <ParkingSpotMap cells={status?.cells ?? []} floor={floor} message={mapMessage} />
      <ParkingFloorLegend />
    </View>
  );
}

// J-01. 주차 도면 전체 보기
export default function ParkingFloorOverviewScreen() {
  const floorScrollRef = useRef<ScrollView>(null);
  const [activeFloor, setActiveFloor] = useState<ParkingFloorKey>('B1');
  const [pageWidth, setPageWidth] = useState(0);
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
  const parkingStatuses = {
    B1: summary ? toParkingStatusDisplay(summary, myZoneNumbers, 'B1') : null,
    B2: summary ? toParkingStatusDisplay(summary, myZoneNumbers, 'B2') : null,
    B3: summary ? toParkingStatusDisplay(summary, myZoneNumbers, 'B3') : null,
  };
  const parkingStatus = parkingStatuses[activeFloor];

  const selectFloor = (floor: ParkingFloorKey) => {
    const floorIndex = PARKING_FLOORS.indexOf(floor);
    setActiveFloor(floor);
    floorScrollRef.current?.scrollTo({ x: floorIndex * pageWidth, animated: true });
  };

  const handleFloorScrollEnd = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    if (pageWidth <= 0) return;
    const nextIndex = Math.round(event.nativeEvent.contentOffset.x / pageWidth);
    const nextFloor = PARKING_FLOORS[nextIndex];
    if (nextFloor) setActiveFloor(nextFloor);
  };

  const handlePressMyCarLocation = () => {
    if (myVehicleLocation) selectFloor(myVehicleLocation);
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
          <SegmentedControl options={FLOOR_TAB_OPTIONS} value={activeFloor} onChange={selectFloor} />

          <View style={styles.mapCard}>
            {parkingStatus ? (
              <View style={styles.congestionRow}>
                <ParkingCongestionBadge
                  level={parkingStatus.congestionLevel}
                  rateLabel={parkingStatus.congestionRateLabel}
                  showMetric={false}
                />
                <ParkingAvailabilityLabel
                  availableCount={parkingStatus.availableCount}
                  congestionLevel={parkingStatus.congestionLevel}
                />
              </View>
            ) : null}

            <View
              style={styles.carouselFrame}
              onLayout={(event) => setPageWidth(event.nativeEvent.layout.width)}
            >
              {pageWidth > 0 ? (
                <ScrollView
                  ref={floorScrollRef}
                  horizontal
                  pagingEnabled
                  directionalLockEnabled
                  nestedScrollEnabled
                  showsHorizontalScrollIndicator={false}
                  style={styles.floorScroll}
                  onMomentumScrollEnd={handleFloorScrollEnd}
                >
                  {PARKING_FLOORS.map((floor) => (
                    <ParkingFloorPage
                      key={floor}
                      floor={floor}
                      status={parkingStatuses[floor]}
                      isLoading={isLoading}
                      hasError={Boolean(error)}
                      width={pageWidth}
                    />
                  ))}
                </ScrollView>
              ) : (
                <ParkingFloorPage
                  floor={activeFloor}
                  status={parkingStatus}
                  isLoading={isLoading}
                  hasError={Boolean(error)}
                />
              )}
            </View>
          </View>
        </Stack>
      </ResponsiveContainer>
    </GradientScreenBackground>
  );
}
