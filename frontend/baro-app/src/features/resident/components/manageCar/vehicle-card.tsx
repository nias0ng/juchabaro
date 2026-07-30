import { LinearGradient } from 'expo-linear-gradient';
import { Text, View } from 'react-native';

import { AppButton } from '@/components/ui';

import type { VehicleResult } from '@/features/auth/api/vehicle-types';

import { maskPlateNumber } from '../../utils/mask-plate-number';

import { styles } from './vehicle-card.styles';

const HOUSEHOLD_CARD_GRADIENT = ['#dcd7fb', '#c9ece7'] as const;
const VISITOR_CARD_GRADIENT = ['#ffdccd', '#dcd7fb'] as const;

type VehicleCardProps = {
  vehicle: VehicleResult;
  onDelete: (vehicle: VehicleResult) => void;
};

/** H-02-1/H-02-2에서 등록된 차량 한 대를 보여주는 카드. */
export function VehicleCard({ vehicle, onDelete }: VehicleCardProps) {
  const isHousehold = vehicle.ownerType === 'RESIDENT';

  return (
    <LinearGradient
      colors={isHousehold ? HOUSEHOLD_CARD_GRADIENT : VISITOR_CARD_GRADIENT}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={styles.card}
    >
      <View style={styles.badge}>
        <Text style={styles.badgeText}>{isHousehold ? '세대 차량 · 입주민' : '방문 차량'}</Text>
      </View>

      <Text style={styles.plate}>{maskPlateNumber(vehicle.plateNumber)}</Text>

      <View style={styles.divider} />

      <View style={styles.infoRow}>
        <Text style={styles.infoLabel}>{isHousehold ? '차종' : '등록 방문일'}</Text>
        <Text style={styles.infoValue}>{(isHousehold ? vehicle.carModel : vehicle.visitDate) ?? '-'}</Text>
      </View>
      <View style={styles.infoRow}>
        <Text style={styles.infoLabel}>전기차 여부</Text>
        <Text style={styles.infoValue}>{vehicle.isElectric ? '해당' : '해당 없음'}</Text>
      </View>
      <View style={styles.infoRow}>
        <Text style={styles.infoLabel}>장애인 등록 차량</Text>
        <Text style={styles.infoValue}>{vehicle.isDisabled ? '해당' : '해당 없음'}</Text>
      </View>

      <View style={styles.deleteButton}>
        <AppButton label="차량 삭제" variant="muted" size="sm" onPress={() => onDelete(vehicle)} />
      </View>
    </LinearGradient>
  );
}
