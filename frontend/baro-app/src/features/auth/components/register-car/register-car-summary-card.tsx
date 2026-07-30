import { LinearGradient } from 'expo-linear-gradient';
import { Text, View, type ColorValue } from 'react-native';

import { styles } from './register-car-summary-card.styles';

const EMPTY_PLATE_MESSAGE = '차량 번호를 입력해 주세요';

type RegisterCarSummaryCardProps = {
  badgeLabel: string;
  gradientColors: readonly [ColorValue, ColorValue, ...ColorValue[]];
  plateNumber: string;
};

/** G-01/G-02 상단의 그라디언트 차량 성격/번호 미리보기 카드. 입력값을 그대로 보여줄 뿐 자체 상태는 없다. */
export function RegisterCarSummaryCard({ badgeLabel, gradientColors, plateNumber }: RegisterCarSummaryCardProps) {
  const trimmedPlateNumber = plateNumber.trim();

  return (
    <LinearGradient
      colors={gradientColors}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={styles.summaryCard}
    >
      <View style={styles.summaryBadge}>
        <Text style={styles.summaryBadgeText}>{badgeLabel}</Text>
      </View>
      <Text style={[styles.summaryPlate, !trimmedPlateNumber && styles.summaryPlatePlaceholder]}>
        {trimmedPlateNumber || EMPTY_PLATE_MESSAGE}
      </Text>
    </LinearGradient>
  );
}
