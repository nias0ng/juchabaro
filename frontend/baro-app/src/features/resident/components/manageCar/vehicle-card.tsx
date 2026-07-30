import { LinearGradient } from 'expo-linear-gradient';
import { Pressable, Text, View } from 'react-native';

import { Palette } from '@/styles';

import type { VehicleApprovalStatus, VehicleResult } from '@/features/auth/api/vehicle-types';

import { styles } from './vehicle-card.styles';
import { VehicleBadgeIcon } from './vehicle-badge-icon';

const HOUSEHOLD_CARD_GRADIENT = [Palette.lavender100, Palette.mint100] as const;
const VISITOR_CARD_GRADIENT = [Palette.peach100, Palette.lavender100] as const;

// TODO(vehicle-api): 백엔드 승인 상태 필드가 확정되면 라벨/색을 다시 확인해야 함.
const APPROVAL_LABEL: Record<VehicleApprovalStatus, string> = {
  APPROVED: '승인됨',
  PENDING: '심사중',
  REJECTED: '반려됨',
};

type VehicleCardProps = {
  vehicle: VehicleResult;
  onDelete: (vehicle: VehicleResult) => void;
};

/** H-02-1/H-02-2에서 등록된 차량 한 대를 보여주는 카드. */
export function VehicleCard({ vehicle, onDelete }: VehicleCardProps) {
  const isHousehold = vehicle.ownerType === 'RESIDENT';
  const approvalStatus = vehicle.approvalStatus ?? 'APPROVED';

  const subtitle = isHousehold ? vehicle.carModel : '24시간 임시 등록';

  const infoItems = isHousehold
    ? [
        { label: '위치', value: vehicle.parkingSpotCode ?? '-' },
        { label: '등록일', value: vehicle.registeredAt ?? '-' },
      ]
    : [
        { label: '방문 시작', value: vehicle.visitStartAt ?? '-' },
        { label: '방문 종료', value: vehicle.visitEndAt ?? '-' },
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
          {vehicle.isDisabled ? <VehicleBadgeIcon name="disabled" /> : null}
          <View style={styles.approvalBadge}>
            <Text style={styles.approvalBadgeText}>{APPROVAL_LABEL[approvalStatus]}</Text>
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
