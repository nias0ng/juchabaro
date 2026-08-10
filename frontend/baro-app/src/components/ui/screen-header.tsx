import { router } from 'expo-router';
import type { ReactNode } from 'react';
import { Text, View, type StyleProp, type TextStyle, type ViewStyle } from 'react-native';

import { Spacing } from '@/styles';

import { BackButton } from './back-button';
import { styles } from './screen-header.styles';
import { Stack } from './stack';

type ScreenHeaderProps = {
  title: string;
  onBack?: () => void;
  right?: ReactNode;
  /** 탭 루트 화면(요청/알림/내 정보)처럼 뒤로가기가 필요 없는 화면에서는 false로 끈다. */
  showBackButton?: boolean;
  style?: StyleProp<ViewStyle>;
  /** 특정 화면에서만 제목 크기·위치를 조정해야 할 때 기본 title 스타일 위에 덧씌운다. */
  titleStyle?: StyleProp<TextStyle>;
};

export function ScreenHeader({ title, onBack, right, showBackButton = true, style, titleStyle }: ScreenHeaderProps) {
  return (
    <Stack direction="row" align="center" gap={Spacing.base} style={[styles.container, style]}>
      {showBackButton ? <BackButton onPress={onBack ?? (() => router.back())} /> : null}
      <Text style={[styles.title, showBackButton ? styles.titleWithBack : styles.titleWithoutBack, titleStyle]}>
        {title}
      </Text>
      {right ? <View style={styles.right}>{right}</View> : null}
    </Stack>
  );
}
