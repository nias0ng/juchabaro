import { Pressable, Text, View } from 'react-native';

import type { ParkingFloorKey, ParkingStatusDisplay } from '../utils/parking-zone';
import { Palette } from '@/styles';

import { ParkingCongestionBadge } from './parking-congestion-badge';
import { ParkingLegend } from './parking-legend';
import { ParkingSpotMap } from './parking-spot-map';
import { styles } from './parking-status-card.styles';

type ParkingStatusCardProps = {
  title: string;
  status: ParkingStatusDisplay | null;
  isLoading?: boolean;
  hasError?: boolean;
  floor?: ParkingFloorKey;
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
            <ParkingCongestionBadge
              level={status.congestionLevel}
              rateLabel={status.congestionRateLabel}
            />
          </View>
        ) : null}

        <ParkingSpotMap cells={status?.cells ?? []} message={mapMessage} floor={floor} />

        <ParkingLegend
          items={[
            { label: '내 차량', color: Palette.yellow100 },
            { label: '사용중', color: Palette.violet300 },
            { label: status ? status.availableLabel : '비어 있음 -', color: Palette.lilac100 },
          ]}
        />
      </View>
    </Pressable>
  );
}
