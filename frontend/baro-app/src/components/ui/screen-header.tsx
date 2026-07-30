import { router } from 'expo-router';
import type { ReactNode } from 'react';
import { Text, View, type StyleProp, type ViewStyle } from 'react-native';

import { Spacing } from '@/styles';

import { BackButton } from './back-button';
import { styles } from './screen-header.styles';
import { Stack } from './stack';

type ScreenHeaderProps = {
  title: string;
  onBack?: () => void;
  right?: ReactNode;
  style?: StyleProp<ViewStyle>;
};

export function ScreenHeader({ title, onBack, right, style }: ScreenHeaderProps) {
  return (
    <Stack direction="row" align="center" gap={Spacing.base} style={[styles.container, style]}>
      <BackButton onPress={onBack ?? (() => router.back())} />
      <Text style={styles.title}>{title}</Text>
      {right ? <View style={styles.right}>{right}</View> : null}
    </Stack>
  );
}
