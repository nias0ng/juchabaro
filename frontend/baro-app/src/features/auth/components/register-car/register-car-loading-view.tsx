import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import { Text, View } from 'react-native';

import { styles } from './register-car-loading-view.styles';

const LOADING_BACKGROUND_GRADIENT = ['#ddf3f0', '#eae7fb'] as const;
const carIcon = require('@/assets/images/auth/register-car-icon.png');

/**
 * G-04. 차량 등록 처리 중 UI만 담당한다.
 * API 호출, navigation, timer는 register-car-screen(또는 훅)에서 처리하고
 * 이 컴포넌트는 isRegistering === true일 때 렌더링되는 오버레이 내용만 그린다.
 */
export function RegisterCarLoadingView() {
  return (
    <LinearGradient
      colors={LOADING_BACKGROUND_GRADIENT}
      start={{ x: 0, y: 0 }}
      end={{ x: 0, y: 1 }}
      style={styles.container}
    >
      <View style={styles.iconShadow}>
        <View style={styles.iconCircle}>
          <Image source={carIcon} style={styles.carIcon} contentFit="cover" />
        </View>
      </View>
      <Text style={styles.title}>등록 처리 중</Text>
      <Text style={styles.description}>차량 등록 정보를 확인하고 있습니다</Text>
    </LinearGradient>
  );
}
