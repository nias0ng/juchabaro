import { Text, View, type ColorValue } from 'react-native';

import { Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import type { RegisterCarType, VisitorCarFormValues } from '../../types/register-car';
import { isPlateNumberValid } from '../../validation/register-car';

import { RegisterCarAvailabilitySection } from './register-car-availability-section';
import { RegisterCarSectionLabel } from './register-car-section-label';
import { RegisterCarSummaryCard } from './register-car-summary-card';
import { RegisterCarTypeSelector } from './register-car-type-selector';
import { VehicleNumberField } from './vehicle-number-field';
import { VisitDateField } from './visit-date-field';
import { styles } from './visitor-car-form.styles';

const SUMMARY_CARD_GRADIENT: readonly [ColorValue, ColorValue] = ['#ffdccd', '#dcd7fb'];

type VisitorCarFormProps = {
  carType: RegisterCarType;
  onChangeCarType: (type: RegisterCarType) => void;
  values: VisitorCarFormValues;
  onChange: <K extends keyof VisitorCarFormValues>(key: K, value: VisitorCarFormValues[K]) => void;
  onOpenVisitDatePicker: () => void;
};

export function VisitorCarForm({
  carType,
  onChangeCarType,
  values,
  onChange,
  onOpenVisitDatePicker,
}: VisitorCarFormProps) {
  const plateValid = isPlateNumberValid(values.plateNumber);

  return (
    <Stack gap={Spacing.base}>
      <RegisterCarSummaryCard
        badgeLabel="방문 차량"
        gradientColors={SUMMARY_CARD_GRADIENT}
        plateNumber={values.plateNumber}
      />

      <Stack gap={Spacing.xs}>
        <RegisterCarSectionLabel>차량 성격</RegisterCarSectionLabel>
        <RegisterCarTypeSelector value={carType} onChange={onChangeCarType} />
      </Stack>

      <VehicleNumberField
        value={values.plateNumber}
        onChangeText={(text) => onChange('plateNumber', text)}
        errorMessage={values.plateNumber.length > 0 && !plateValid ? '차량 번호 형식을 확인해 주세요' : undefined}
      />

      <VisitDateField value={values.visitDate} onPress={onOpenVisitDatePicker} />

      <RegisterCarAvailabilitySection
        title="이용 가능 구역"
        isElectric={values.isElectric}
        onChangeElectric={(checked) => onChange('isElectric', checked)}
        isDisabled={values.isDisabled}
        onChangeDisabled={(checked) => onChange('isDisabled', checked)}
      />

      <View style={styles.noticeBanner}>
        <Text style={styles.noticeText}>{'방문 차량은 등록 후 24시간 동안만 유효하며,\n이후 자동으로 목록에서 제거됩니다.'}</Text>
      </View>
    </Stack>
  );
}
