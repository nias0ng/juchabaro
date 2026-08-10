import { useRef, useState } from 'react';
import {
  Pressable,
  ScrollView,
  Text,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native';

import {
  PARKING_FLOORS,
  type ParkingFloorKey,
  type ParkingStatusDisplay,
} from '../utils/parking-zone';
import { Palette } from '@/styles';

import { ParkingAvailabilityLabel } from './parking-availability-label';
import { ParkingCongestionBadge } from './parking-congestion-badge';
import { ParkingLegend } from './parking-legend';
import { ParkingSpotMap } from './parking-spot-map';
import { styles } from './parking-status-card.styles';

type ParkingStatusCardProps = {
  title: string;
  statuses: Record<ParkingFloorKey, ParkingStatusDisplay | null>;
  isLoading?: boolean;
  hasError?: boolean;
  onPress?: () => void;
};

type FloorPageProps = {
  floor: ParkingFloorKey;
  status: ParkingStatusDisplay | null;
  isLoading: boolean;
  hasError: boolean;
  width: number;
  onPress?: () => void;
};

function FloorPage({
  floor,
  status,
  isLoading,
  hasError,
  width,
  onPress,
}: FloorPageProps) {
  const hasParkingData = Boolean(status && status.cells.length > 0);
  const mapMessage = isLoading
    ? '주차 현황을 불러오는 중입니다'
    : hasError
      ? '주차 현황을 불러오지 못했습니다'
      : !hasParkingData
        ? '해당 층의 주차 현황이 없습니다'
      : undefined;

  return (
    <Pressable
      style={[styles.floorPage, { width }]}
      disabled={!onPress}
      accessibilityRole={onPress ? 'button' : undefined}
      accessibilityLabel={`${floor} 주차 현황`}
      onPress={onPress}
    >
      <ParkingSpotMap cells={status?.cells ?? []} message={mapMessage} floor={floor} />

      <ParkingLegend
        items={[
          { label: '내 차량', color: Palette.yellow100 },
          { label: '사용중', color: Palette.violet300 },
          { label: '비어 있음', color: Palette.lilac100 },
        ]}
      />
    </Pressable>
  );
}

export function ParkingStatusCard({
  title,
  statuses,
  isLoading = false,
  hasError = false,
  onPress,
}: ParkingStatusCardProps) {
  const scrollRef = useRef<ScrollView>(null);
  const [activeFloor, setActiveFloor] = useState<ParkingFloorKey>('B1');
  const [pageWidth, setPageWidth] = useState(0);
  const activeStatus = statuses[activeFloor];
  const hasActiveParkingData = Boolean(activeStatus && activeStatus.cells.length > 0);

  const selectFloor = (floor: ParkingFloorKey) => {
    const floorIndex = PARKING_FLOORS.indexOf(floor);
    setActiveFloor(floor);
    scrollRef.current?.scrollTo({ x: floorIndex * pageWidth, animated: true });
  };

  const handleScrollEnd = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    if (pageWidth <= 0) return;
    const nextIndex = Math.round(event.nativeEvent.contentOffset.x / pageWidth);
    const nextFloor = PARKING_FLOORS[nextIndex];
    if (nextFloor) setActiveFloor(nextFloor);
  };

  return (
    <View style={styles.container}>
      <View style={styles.headerRow}>
        <Text style={styles.title}>{title}</Text>
      </View>
      <View style={styles.card}>
        <View style={styles.cardHeaderRow}>
          <View style={styles.floorTabs}>
            {PARKING_FLOORS.map((floor) => {
              const isActive = activeFloor === floor;
              return (
                <Pressable
                  key={floor}
                  accessibilityRole="tab"
                  accessibilityState={{ selected: isActive }}
                  style={[styles.floorTab, isActive && styles.floorTabActive]}
                  onPress={() => selectFloor(floor)}
                >
                  <Text style={[styles.floorTabText, isActive && styles.floorTabTextActive]}>
                    {floor}
                  </Text>
                </Pressable>
              );
              })}
            </View>
          {hasActiveParkingData && activeStatus ? (
            <View style={styles.cardSummaryRow}>
              <ParkingCongestionBadge
                level={activeStatus.congestionLevel}
                rateLabel={activeStatus.congestionRateLabel}
                showMetric={false}
              />
              <ParkingAvailabilityLabel
                availableCount={activeStatus.availableCount}
                congestionLevel={activeStatus.congestionLevel}
              />
            </View>
          ) : null}
        </View>
        <View
          style={styles.carouselFrame}
          onLayout={(event) => setPageWidth(event.nativeEvent.layout.width)}
        >
          {pageWidth > 0 ? (
            <ScrollView
              ref={scrollRef}
              horizontal
              pagingEnabled
              directionalLockEnabled
              nestedScrollEnabled
              showsHorizontalScrollIndicator={false}
              style={styles.floorScroll}
              onMomentumScrollEnd={handleScrollEnd}
            >
              {PARKING_FLOORS.map((floor) => (
                <FloorPage
                  key={floor}
                  floor={floor}
                  status={statuses[floor]}
                  isLoading={isLoading}
                  hasError={hasError}
                  width={pageWidth}
                  onPress={onPress}
                />
              ))}
            </ScrollView>
          ) : (
            <FloorPage
              floor={activeFloor}
              status={statuses[activeFloor]}
              isLoading={isLoading}
              hasError={hasError}
              width={0}
              onPress={onPress}
            />
          )}
        </View>
      </View>
    </View>
  );
}
