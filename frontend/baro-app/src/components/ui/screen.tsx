import type { ReactNode } from 'react';
import {
  ScrollView,
  View,
  type ScrollViewProps,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView, type Edge } from 'react-native-safe-area-context';

import { useTheme } from '@/hooks/use-theme';

import { styles } from './screen.styles';

type ScreenProps = {
  children: ReactNode;
  scroll?: boolean;
  backgroundColor?: string;
  edges?: Edge[];
  style?: StyleProp<ViewStyle>;
  contentContainerStyle?: StyleProp<ViewStyle>;
  keyboardShouldPersistTaps?: ScrollViewProps['keyboardShouldPersistTaps'];
};

export function Screen({
  children,
  scroll = false,
  backgroundColor,
  edges = ['top', 'right', 'bottom', 'left'],
  style,
  contentContainerStyle,
  keyboardShouldPersistTaps = 'handled',
}: ScreenProps) {
  const theme = useTheme();
  const screenStyle = [
    styles.safeArea,
    { backgroundColor: backgroundColor ?? theme.background },
    style,
  ];

  if (scroll) {
    return (
      <SafeAreaView style={screenStyle} edges={edges}>
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={[styles.content, contentContainerStyle]}
          keyboardShouldPersistTaps={keyboardShouldPersistTaps}
          showsVerticalScrollIndicator={false}
        >
          {children}
        </ScrollView>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={screenStyle} edges={edges}>
      <View style={[styles.content, contentContainerStyle]}>{children}</View>
    </SafeAreaView>
  );
}
