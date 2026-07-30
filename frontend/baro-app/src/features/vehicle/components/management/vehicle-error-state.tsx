import { Text, View } from 'react-native';

import { AppButton } from '@/components/ui';

import { styles } from './vehicle-error-state.styles';

type VehicleErrorStateProps = {
  message: string;
  onRetry: () => void;
};

/** 차량 목록 조회에 실패했을 때 빈 상태(H-01)와 구분해서 보여주는 오류 상태. */
export function VehicleErrorState({ message, onRetry }: VehicleErrorStateProps) {
  return (
    <View style={styles.container}>
      <Text style={styles.icon}>⚠️</Text>
      <Text style={styles.heading}>차량 목록을 불러오지 못했습니다</Text>
      <Text style={styles.message}>{message}</Text>
      <AppButton label="다시 시도" variant="muted" size="md" onPress={onRetry} />
    </View>
  );
}
