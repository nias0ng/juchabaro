import { Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import { RegisterCarSectionLabel } from './register-car-section-label';
import { RegisterCarToggleRow } from './register-car-toggle-row';

type RegisterCarAvailabilitySectionProps = {
  title: string;
  isElectric: boolean;
  onChangeElectric: (value: boolean) => void;
  isDisabled: boolean;
  onChangeDisabled: (value: boolean) => void;
};

/**
 * "이용 가능 구역" 섹션. 전기차/장애인 등록 차량 두 항목은 G-01, G-02에서 항상 동일하게 쓰여서
 * 임의 옵션 배열 대신 현재 실제로 존재하는 두 항목을 그대로 props로 받는다.
 */
export function RegisterCarAvailabilitySection({
  title,
  isElectric,
  onChangeElectric,
  isDisabled,
  onChangeDisabled,
}: RegisterCarAvailabilitySectionProps) {
  return (
    <Stack gap={Spacing.xs}>
      <RegisterCarSectionLabel>{title}</RegisterCarSectionLabel>
      <Stack gap={Spacing.sm}>
        <RegisterCarToggleRow
          label="전기차 여부"
          description="전기차 전용 구역 이용 가능"
          value={isElectric}
          onChange={onChangeElectric}
        />
        <RegisterCarToggleRow
          label="장애인 등록 차량"
          description="장애인 전용 구역 이용 가능"
          value={isDisabled}
          onChange={onChangeDisabled}
        />
      </Stack>
    </Stack>
  );
}
