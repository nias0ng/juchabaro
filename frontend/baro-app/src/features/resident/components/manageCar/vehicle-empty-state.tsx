import { LinearGradient } from 'expo-linear-gradient';
import { Text, View } from 'react-native';

import { AppButton } from '@/components/ui';

import { styles } from './vehicle-empty-state.styles';

const EMPTY_ICON_GRADIENT = ['#8b7ff0', '#6fcfc4'] as const;

type VehicleEmptyStateProps = {
  onAddVehicle: () => void;
};

/** H-01. 등록된 차량이 없을 때 표시하는 빈 상태 화면. */
export function VehicleEmptyState({ onAddVehicle }: VehicleEmptyStateProps) {
  return (
    <View style={styles.container}>
      <View style={styles.iconCircle}>
        <LinearGradient
          colors={EMPTY_ICON_GRADIENT}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={styles.iconGradient}
        />
      </View>

      <Text style={styles.heading}>{'등록된 차량이\n없습니다'}</Text>
      <Text style={styles.description}>
        {'차량을 등록하면 아파트 내 주차\n서비스를 편리하게 이용할 수 있어요.'}
      </Text>

      <View style={styles.actions}>
        <AppButton label="차량 추가하기" variant="neutral" size="lg" fullWidth onPress={onAddVehicle} />
      </View>
    </View>
  );
}
