import { LinearGradient } from 'expo-linear-gradient';
import { Text, View } from 'react-native';

import { useColorTokens } from '@/hooks/use-color-tokens';
import { useThemedStyles } from '@/hooks/use-themed-styles';

import { createStyles } from './request-check-badge.styles';

type RequestCheckBadgeProps = {
  outerSize?: number;
  innerSize?: number;
  gradientColors?: readonly [string, string, ...string[]];
};

/**
 * 흰 원(그림자) 안에 그라디언트 원 + 체크 표시를 넣은 배지. 이동 완료(E-13)와 요청 전송 완료(E-03)에서
 * 크기/색만 다르게 재사용한다.
 */
export function RequestCheckBadge({
  outerSize = 64,
  innerSize = 26,
  gradientColors,
}: RequestCheckBadgeProps) {
  const styles = useThemedStyles(createStyles);
  const t = useColorTokens();

  return (
    <View
      style={[
        styles.outer,
        { width: outerSize, height: outerSize, borderRadius: outerSize / 2 },
      ]}
    >
      <LinearGradient
        colors={gradientColors ?? t.gradient.accent}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={[
          styles.inner,
          { width: innerSize, height: innerSize, borderRadius: innerSize / 2 },
        ]}
      >
        <Text style={[styles.check, { fontSize: innerSize / 2 }]}>✓</Text>
      </LinearGradient>
    </View>
  );
}
