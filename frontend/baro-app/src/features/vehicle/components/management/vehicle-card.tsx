import { LinearGradient } from 'expo-linear-gradient';
import { Pressable, Text, View } from 'react-native';

import { Palette } from '@/styles';

import type { VehicleResult, VehicleStatus } from '../../api/types';

import { styles } from './vehicle-card.styles';
import { VehicleBadgeIcon } from './vehicle-badge-icon';

const HOUSEHOLD_CARD_GRADIENT = [Palette.lavender100, Palette.mint100] as const;
const VISITOR_CARD_GRADIENT = [Palette.peach100, Palette.lavender100] as const;

const STATUS_LABEL: Record<VehicleStatus, string> = {
  ACTIVE: '승인됨',
  PENDING: '심사중',
  DELETED: '삭제됨',
};

/** 상세 조회 응답의 createdAt(ISO, 타임존 포함)을 "YYYY.MM.DD"로 변환한다. */
function formatRegisteredDate(createdAt: string | undefined): string {
  if (!createdAt) return '-';

  const date = new Date(createdAt);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');

  return `${year}.${month}.${day}`;
}

type VehicleCardProps = {
  vehicle: VehicleResult;
  onDelete: (vehicle: VehicleResult) => void;
};

/** H-02-1/H-02-2에서 등록된 차량 한 대를 보여주는 카드. */
export function VehicleCard({ vehicle, onDelete }: VehicleCardProps) {
  const isHousehold = vehicle.ownerType === 'RESIDENT';

  const subtitle = isHousehold ? vehicle.vehicleModel : '임시 등록';

  const infoItems = [
    { label: '위치', value: vehicle.parkingSpotCode ?? '-' },
    { label: '등록일', value: formatRegisteredDate(vehicle.createdAt) },
  ];

  return (
    <LinearGradient
      colors={isHousehold ? HOUSEHOLD_CARD_GRADIENT : VISITOR_CARD_GRADIENT}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={styles.card}
    >
      <View style={styles.topRow}>
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{isHousehold ? '세대 차량' : '방문 차량'}</Text>
        </View>

        <View style={styles.statusGroup}>
          {vehicle.isElectric ? <VehicleBadgeIcon name="electric" /> : null}
          {vehicle.isDisabledVehicle ? <VehicleBadgeIcon name="disabled" /> : null}
          <View style={styles.approvalBadge}>
            <Text style={styles.approvalBadgeText}>{STATUS_LABEL[vehicle.status]}</Text>
          </View>
        </View>
      </View>

      <View style={styles.plateGroup}>
        <Text style={styles.plate}>{vehicle.plateNumber}</Text>
        <Text style={styles.subtitle}>{subtitle}</Text>
      </View>

      <View style={styles.infoRow}>
        {infoItems.map((item) => (
          <View key={item.label} style={styles.infoBox}>
            <Text style={styles.infoLabel}>{item.label}</Text>
            <Text style={styles.infoValue}>{item.value}</Text>
          </View>
        ))}
      </View>

      <Pressable
        accessibilityRole="button"
        style={({ pressed }) => [styles.deleteButton, pressed && styles.deleteButtonPressed]}
        onPress={() => onDelete(vehicle)}
      >
        <Text style={styles.deleteButtonText}>차량 삭제</Text>
      </Pressable>
    </LinearGradient>
  );
}
