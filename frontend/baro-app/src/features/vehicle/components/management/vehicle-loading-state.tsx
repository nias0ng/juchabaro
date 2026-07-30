import { ActivityIndicator, Text, View } from 'react-native';

import { useTheme } from '@/hooks/use-theme';

import { styles } from './vehicle-loading-state.styles';

/** 차량 목록을 조회하는 동안 표시하는 로딩 상태. */
export function VehicleLoadingState() {
  const theme = useTheme();

  return (
    <View style={styles.container}>
      <ActivityIndicator color={theme.primary} size="large" />
      <Text style={styles.text}>차량 목록을 불러오고 있습니다</Text>
    </View>
  );
}
