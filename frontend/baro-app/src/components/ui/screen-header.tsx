import { router } from 'expo-router';
import type { ReactNode } from 'react';
import { Pressable, Text, View, type StyleProp, type ViewStyle } from 'react-native';

import { styles } from './screen-header.styles';

type ScreenHeaderProps = {
  title: string;
  onBack?: () => void;
  /** 뒤로가기/제목 옆에 붙는 오른쪽 콘텐츠 (예: 배지). 없으면 렌더링하지 않는다. */
  right?: ReactNode;
  style?: StyleProp<ViewStyle>;
};

export function ScreenHeader({ title, onBack, right, style }: ScreenHeaderProps) {
  return (
    <View style={[styles.container, style]}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="뒤로 가기"
        style={styles.backButton}
        onPress={onBack ?? (() => router.back())}
      >
        <View style={styles.backIcon} />
      </Pressable>

      <Text style={styles.title}>{title}</Text>

      {right}
    </View>
  );
}
