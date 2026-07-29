import { LinearGradient } from 'expo-linear-gradient';
import { Text, View } from 'react-native';

import { Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import type { RegisterCarType, VisitorCarFormValues } from '../../types/register-car';
import {
  VISIT_DATE_MAX_LENGTH,
  formatVisitDate,
  isPlateNumberValid,
  isVisitDateValid,
} from '../../validation/register-car';

import { TextField } from '../text-field';
import { RegisterCarToggleRow } from './register-car-toggle-row';
import { RegisterCarTypeSelector } from './register-car-type-selector';
import { styles } from './visitor-car-form.styles';

const SUMMARY_CARD_GRADIENT = ['#ffdccd', '#dcd7fb'] as const;

type VisitorCarFormProps = {
  carType: RegisterCarType;
  onChangeCarType: (type: RegisterCarType) => void;
  values: VisitorCarFormValues;
  onChange: <K extends keyof VisitorCarFormValues>(key: K, value: VisitorCarFormValues[K]) => void;
};

export function VisitorCarForm({ carType, onChangeCarType, values, onChange }: VisitorCarFormProps) {
  const plateValid = isPlateNumberValid(values.plateNumber);
  const visitDateValid = isVisitDateValid(values.visitDate);

  return (
    <Stack gap={Spacing.base}>
      <LinearGradient
        colors={SUMMARY_CARD_GRADIENT}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={styles.summaryCard}
      >
        <View style={styles.summaryBadge}>
          <Text style={styles.summaryBadgeText}>방문 차량</Text>
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
        error={values.plateNumber.length > 0 && !plateValid ? '차량 번호 형식을 확인해 주세요' : undefined}
      />

      <TextField
        label="등록 방문일"
        value={values.visitDate}
        onChangeText={(text) => onChange('visitDate', formatVisitDate(text))}
        placeholder="2025.01.01"
        keyboardType="number-pad"
        maxLength={VISIT_DATE_MAX_LENGTH}
        error={values.visitDate.length > 0 && !visitDateValid ? 'YYYY.MM.DD 형식으로 입력해 주세요' : undefined}
      />

      <Stack gap={Spacing.xs}>
        <Text style={styles.sectionLabel}>이용 가능 구역</Text>
        <Stack gap={Spacing.sm}>
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
      </Stack>

      <View style={styles.noticeBanner}>
        <Text style={styles.noticeText}>
          방문 차량은 등록 후 24시간 동안만 유효하며, 이후 자동으로 목록에서 제거됩니다.
        </Text>
      </View>
    </Stack>
  );
}
