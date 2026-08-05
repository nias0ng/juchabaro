import { Pressable, Text, View } from 'react-native';

import type { ParkingFloorKey, ParkingStatusDisplay } from '../utils/parking-zone';
import { Palette } from '@/styles';

import { ParkingLegend } from './parking-legend';
import { ParkingSpotMap } from './parking-spot-map';
import { styles } from './parking-status-card.styles';

type ParkingStatusCardProps = {
  title: string;
  status: ParkingStatusDisplay | null;
  isLoading?: boolean;
  hasError?: boolean;
  floor?: ParkingFloorKey;
  /** 있으면 카드 전체를 눌러서 주차 도면 전체 보기 등으로 이동할 수 있게 된다. */
  onPress?: () => void;
};

export function ParkingStatusCard({
  title,
  status,
  isLoading = false,
  hasError = false,
  floor,
  onPress,
}: ParkingStatusCardProps) {
  const congestionColorStyle =
    status?.congestionLevel === 'LOW'
      ? styles.congestionTextLow
      : status?.congestionLevel === 'HIGH'
        ? styles.congestionTextHigh
        : styles.congestionTextMedium;

  const mapMessage = isLoading
    ? '주차 현황을 불러오는 중입니다'
    : hasError
      ? '주차 현황을 불러오지 못했습니다'
      : !status
        ? '표시할 주차 현황이 없습니다'
        : undefined;

  return (
    <Pressable
      style={styles.container}
      disabled={!onPress}
      accessibilityRole={onPress ? 'button' : undefined}
      onPress={onPress}
    >
      <View style={styles.headerRow}>
        <Text style={styles.title}>{title}</Text>
      </View>
      <View style={styles.card}>
        {status ? (
          <View style={styles.congestionPill}>
            <Text style={[styles.congestionText, congestionColorStyle]}>
              {status.congestionLabel}
            </Text>
          </View>
        ) : null}

        <ParkingSpotMap cells={status?.cells ?? []} message={mapMessage} floor={floor} />

        <ParkingLegend
          items={[
            { label: status ? status.occupiedLabel : '주차 중 -', color: Palette.violet300 },
            { label: status ? status.availableLabel : '비어 있음 -', color: Palette.gray100 },
            { label: '충전구역', color: Palette.teal100 },
            { label: '장애인구역', color: Palette.sky100 },
            { label: status ? status.violationLabel : '위반 -', color: Palette.peach100 },
          ]}
        />
      </View>
    </Pressable>
  );
}
