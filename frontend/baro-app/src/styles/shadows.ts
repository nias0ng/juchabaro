import type { ViewStyle } from 'react-native';

import { Palette } from './colors';

type ShadowStyle = Pick<ViewStyle, 'shadowColor' | 'shadowOffset' | 'shadowOpacity' | 'shadowRadius' | 'elevation'>;

// 카드형 UI(알림/요청/주차 현황 등)에서 반복되는 기본 그림자.
export const Shadows: Record<'card', ShadowStyle> = {
  card: {
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.06,
    shadowRadius: 13,
    elevation: 2,
  },
};
