import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { GradientScreenBackground, ResponsiveContainer, ScreenHeader, SegmentedControl, Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import { ParkingFloorGrid } from '../components/parking-floor-grid';
import { ParkingFloorLegend } from '../components/parking-floor-legend';
import {
  MOCK_PARKING_FLOORS,
  getMyVehicleLocation,
  type ParkingFloorKey,
} from '../mocks/parking-floor-overview.mock';
import { useParkingSessions } from '../hooks/use-parking-sessions';

import { styles } from './parking-floor-overview-screen.styles';

const FLOOR_TAB_OPTIONS = MOCK_PARKING_FLOORS.map((floor) => ({ key: floor.key, label: floor.label }));

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
  const [activeFloor, setActiveFloor] = useState<ParkingFloorKey>(MOCK_PARKING_FLOORS[0].key);
  const { sessions } = useParkingSessions();
  const myVehicleLocation = getMyVehicleLocation(sessions);

  const currentFloor =
    MOCK_PARKING_FLOORS.find((floor) => floor.key === activeFloor) ?? MOCK_PARKING_FLOORS[0];

  const handlePressMyCarLocation = () => {
    if (myVehicleLocation) setActiveFloor(myVehicleLocation.floorKey);
  };

  return (
    <GradientScreenBackground>
      <ScreenHeader
        title="주차 현황"
        style={styles.header}
        onBack={goBack}
        right={
          <Pressable accessibilityRole="button" onPress={handlePressMyCarLocation}>
            <Text style={styles.headerAction}>내 차 위치</Text>
          </Pressable>
        }
      />

      <ResponsiveContainer style={styles.content}>
        <Stack gap={Spacing.base + 2}>
          <SegmentedControl options={FLOOR_TAB_OPTIONS} value={activeFloor} onChange={setActiveFloor} />

          <View style={styles.mapCard}>
            {/* TODO: 주차 구역 API 및 DB 구축 후 실제 주차 현황 데이터로 교체 */}
            <ParkingFloorGrid spots={currentFloor.spots} sideSpots={currentFloor.sideSpots} />
            <ParkingFloorLegend />
          </View>
        </Stack>
      </ResponsiveContainer>
    </GradientScreenBackground>
  );
}
