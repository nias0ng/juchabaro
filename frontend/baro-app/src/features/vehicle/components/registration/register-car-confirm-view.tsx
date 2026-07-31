import { LinearGradient } from 'expo-linear-gradient';
import { Text, View } from 'react-native';

import { AppButton, Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import type {
  HouseholdCarFormValues,
  RegisterCarType,
  VisitorCarFormValues,
} from '../../types/register-car';

import { styles } from './register-car-confirm-view.styles';

const HOUSEHOLD_CARD_GRADIENT = ['#dcd7fb', '#c9ece7'] as const;
const VISITOR_CARD_GRADIENT = ['#ffdccd', '#dcd7fb'] as const;

type RegisterCarConfirmViewProps = {
  carType: RegisterCarType;
  household: HouseholdCarFormValues;
  visitor: VisitorCarFormValues;
  isRegistering: boolean;
  onConfirm: () => void;
  onEdit: () => void;
};

export function RegisterCarConfirmView({
  carType,
  household,
  visitor,
  isRegistering,
  onConfirm,
  onEdit,
}: RegisterCarConfirmViewProps) {
  const isHousehold = carType === 'household';
  const plateNumber = isHousehold ? household.plateNumber : visitor.plateNumber;
  const isElectric = isHousehold ? household.isElectric : visitor.isElectric;
  const isDisabled = isHousehold ? household.isDisabled : visitor.isDisabled;

  return (
    <Stack gap={Spacing.base}>
      <Stack gap={Spacing.xxs}>
        <Text style={styles.heading}>{'정보가\n맞으신가요?'}</Text>
        <Text style={styles.description}>입력하신 정보가 정확한지 확인해주세요.</Text>
      </Stack>

      <LinearGradient
        colors={isHousehold ? HOUSEHOLD_CARD_GRADIENT : VISITOR_CARD_GRADIENT}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={styles.summaryCard}
      >
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{isHousehold ? '세대 차량 · 입주민' : '방문 차량'}</Text>
        </View>

        <Text style={styles.plate}>{plateNumber}</Text>

        <View style={styles.divider} />

        <Text style={styles.sectionTitle}>{isHousehold ? '차량 정보' : '방문 정보'}</Text>
        {isHousehold ? (
          <SummaryRow label="차종" value={household.carModel} />
        ) : (
          <SummaryRow label="등록 방문일" value={visitor.visitDate} />
        )}
        <SummaryRow label="전기차 여부" value={isElectric ? '해당' : '해당 없음'} />
        <SummaryRow label="장애인 등록 차량" value={isDisabled ? '해당' : '해당 없음'} />
      </LinearGradient>

      <Stack gap={Spacing.sm}>
        <AppButton
          label="등록 완료하기"
          variant="neutral"
          size="lg"
          fullWidth
          loading={isRegistering}
          onPress={onConfirm}
        />
        <AppButton
          label="수정하기"
          variant="muted"
          size="md"
          fullWidth
          disabled={isRegistering}
          onPress={onEdit}
        />
      </Stack>
    </Stack>
  );
}

type SummaryRowProps = {
  label: string;
  value: string;
};

function SummaryRow({ label, value }: SummaryRowProps) {
  return (
    <View style={styles.summaryRow}>
      <Text style={styles.summaryRowLabel}>{label}</Text>
      <Text style={styles.summaryRowValue}>{value}</Text>
    </View>
  );
}
