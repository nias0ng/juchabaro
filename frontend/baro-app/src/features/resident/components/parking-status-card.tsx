import { Text, View } from 'react-native';

import type { ParkingStatusDisplay } from '@/features/resident/utils/parking-zone';
import { Palette } from '@/styles';

import { ParkingSpotMap } from './parking-spot-map';
import { styles } from './parking-status-card.styles';

type ParkingStatusCardProps = {
  title: string;
  status: ParkingStatusDisplay | null;
  isLoading?: boolean;
  hasError?: boolean;
};

export function ParkingStatusCard({
  title,
  status,
  isLoading = false,
  hasError = false,
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
    <View style={styles.container}>
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

        <ParkingSpotMap cells={status?.cells ?? []} message={mapMessage} />

        <View style={styles.legendRow}>
          <View style={styles.legendItem}>
            <View style={[styles.legendDot, { backgroundColor: Palette.violet300 }]} />
            <Text style={styles.legendText}>{status ? status.occupiedLabel : '주차 중 -'}</Text>
          </View>
          <View style={styles.legendItem}>
            <View style={[styles.legendDot, { backgroundColor: Palette.gray100 }]} />
            <Text style={styles.legendText}>{status ? status.availableLabel : '비어 있음 -'}</Text>
          </View>
          <View style={styles.legendItem}>
            <View style={[styles.legendDot, { backgroundColor: Palette.teal100 }]} />
            <Text style={styles.legendText}>충전구역</Text>
          </View>
          <View style={styles.legendItem}>
            <View style={[styles.legendDot, { backgroundColor: Palette.sky100 }]} />
            <Text style={styles.legendText}>장애인구역</Text>
          </View>
          <View style={styles.legendItem}>
            <View style={[styles.legendDot, { backgroundColor: Palette.peach100 }]} />
            <Text style={styles.legendText}>{status ? status.violationLabel : '위반 -'}</Text>
          </View>
        </View>
      </View>

    </View>
  );
}
