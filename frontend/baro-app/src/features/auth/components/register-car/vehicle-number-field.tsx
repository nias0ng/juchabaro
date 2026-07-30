import { TextField } from '../text-field';

const PLATE_NUMBER_PLACEHOLDER = '12가 3456';

type VehicleNumberFieldProps = {
  value: string;
  onChangeText: (value: string) => void;
  errorMessage?: string;
};

/** G-01/G-02 공통 차량 번호 입력 필드. */
export function VehicleNumberField({ value, onChangeText, errorMessage }: VehicleNumberFieldProps) {
  return (
    <TextField
      label="차량 번호"
      value={value}
      onChangeText={onChangeText}
      placeholder={PLATE_NUMBER_PLACEHOLDER}
      error={errorMessage}
    />
  );
}
