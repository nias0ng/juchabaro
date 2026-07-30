import { formatPlateNumberInput } from '../../validation/register-car';
import { TextField } from '@/components/ui';

const PLATE_NUMBER_PLACEHOLDER = '12가 3456';

type VehicleNumberFieldProps = {
  value: string;
  onChangeText: (value: string) => void;
  errorMessage?: string;
};

/** G-01/G-02 공통 차량 번호 입력 필드. 숫자 2~3자리+한글 1자+띄어쓰기+숫자 4자리 형식으로 입력을 강제한다. */
export function VehicleNumberField({ value, onChangeText, errorMessage }: VehicleNumberFieldProps) {
  return (
    <TextField
      label="차량 번호"
      value={value}
      onChangeText={(text) => onChangeText(formatPlateNumberInput(text))}
      placeholder={PLATE_NUMBER_PLACEHOLDER}
      error={errorMessage}
    />
  );
}
