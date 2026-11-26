import type { ReactNode } from 'react';
import type { StyleProp, ViewStyle } from 'react-native';
import type { Edge } from 'react-native-safe-area-context';

import { useColorTokens } from '@/hooks/use-color-tokens';

import { Screen } from './screen';

// resident/my-page(Figma I-01) 배경 그라데이션. 상단 40%에서 색이 다 바뀌고 그 아래는 옅은 색으로 고정된다.
const GRADIENT_LOCATIONS = [0, 0.4, 1] as const;

type GradientScreenBackgroundProps = {
  children: ReactNode;
  scroll?: boolean;
  edges?: Edge[];
  style?: StyleProp<ViewStyle>;
  contentContainerStyle?: StyleProp<ViewStyle>;
  avoidKeyboard?: boolean;
  refreshing?: boolean;
  onRefresh?: () => void;
};

/** resident 탭 루트 화면(요청/알림/내 정보)이 공유하는 배경 그라데이션. Screen 위에 색상만 고정해서 얹는다. */
export function GradientScreenBackground({
  children,
  scroll = true,
  edges = ['top', 'right', 'left'],
  style,
  contentContainerStyle,
  avoidKeyboard = false,
  refreshing,
  onRefresh,
}: GradientScreenBackgroundProps) {
  const t = useColorTokens();

  return (
    <Screen
      scroll={scroll}
      edges={edges}
      backgroundGradient={t.gradient.brand}
      backgroundGradientLocations={GRADIENT_LOCATIONS}
      style={style}
      contentContainerStyle={contentContainerStyle}
      avoidKeyboard={avoidKeyboard}
      refreshing={refreshing}
      onRefresh={onRefresh}
    >
      {children}
    </Screen>
  );
}
