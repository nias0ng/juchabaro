import { LinearGradient } from 'expo-linear-gradient';
import { Text, View } from 'react-native';

import { Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import type { HouseholdCarFormValues, RegisterCarType } from '../../types/register-car';
import { isCarModelValid, isPlateNumberValid } from '../../validation/register-car';

import { TextField } from '../text-field';
import { RegisterCarToggleRow } from './register-car-toggle-row';
import { RegisterCarTypeSelector } from './register-car-type-selector';
import { styles } from './household-car-form.styles';

const SUMMARY_CARD_GRADIENT = ['#dcd7fb', '#c9ece7'] as const;

type HouseholdCarFormProps = {
  carType: RegisterCarType;
  onChangeCarType: (type: RegisterCarType) => void;
  values: HouseholdCarFormValues;
  onChange: <K extends keyof HouseholdCarFormValues>(key: K, value: HouseholdCarFormValues[K]) => void;
};

export function HouseholdCarForm({ carType, onChangeCarType, values, onChange }: HouseholdCarFormProps) {
  const plateValid = isPlateNumberValid(values.plateNumber);
  const carModelValid = isCarModelValid(values.carModel);

  return (
    <Stack gap={Spacing.base}>
      <LinearGradient
        colors={SUMMARY_CARD_GRADIENT}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={styles.summaryCard}
      >
        <View style={styles.summaryBadge}>
          <Text style={styles.summaryBadgeText}>세대 차량</Text>
        </View>
        <Text style={styles.summaryPlate}>{values.plateNumber.trim() || '차량 번호를 입력해 주세요'}</Text>
      </LinearGradient>

      <Stack gap={Spacing.xs}>
        <Text style={styles.sectionLabel}>차량 성격</Text>
        <RegisterCarTypeSelector value={carType} onChange={onChangeCarType} />
      </Stack>

      <TextField
        label="차량 번호"
        value={values.plateNumber}
        onChangeText={(text) => onChange('plateNumber', text)}
        placeholder="12가 3456"
        rightAdornment={<Text style={styles.cameraIcon}>{'📷'}</Text>}
        error={values.plateNumber.length > 0 && !plateValid ? '차량 번호 형식을 확인해 주세요' : undefined}
      />

      <TextField
        label="차종"
        value={values.carModel}
        onChangeText={(text) => onChange('carModel', text)}
        placeholder="예 : 아이오닉 5"
        error={values.carModel.length > 0 && !carModelValid ? '차종을 입력해 주세요' : undefined}
      />

      <RegisterCarToggleRow
        label="전기차 여부"
        description="전기차 전용 구역 이용 가능"
        value={values.isElectric}
        onChange={(checked) => onChange('isElectric', checked)}
      />

      <RegisterCarToggleRow
        label="장애인 등록 차량"
        description="장애인 전용 구역 이용 가능"
        value={values.isDisabled}
        onChange={(checked) => onChange('isDisabled', checked)}
      />
    </Stack>
  );
}
