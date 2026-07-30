import { Text } from 'react-native';

import { TextField } from '@/components/ui';
import { styles } from './visit-date-field.styles';

const VISIT_DATE_PLACEHOLDER = '2025.01.01';

const noop = () => {};

type VisitDateFieldProps = {
  value: string;
  onPress: () => void;
};

/**
 * 등록 방문일 필드. 키보드로 직접 입력하지 못하도록 항상 editable={false}로 두고,
 * 필드 전체를 누르면 onPress(date picker 열기)만 호출한다.
 */
export function VisitDateField({ value, onPress }: VisitDateFieldProps) {
  return (
    <TextField
      label="등록 방문일"
      value={value}
      onChangeText={noop}
      editable={false}
      onPress={onPress}
      placeholder={VISIT_DATE_PLACEHOLDER}
      rightAdornment={<Text style={styles.calendarIcon}>{'📅'}</Text>}
    />
  );
}
