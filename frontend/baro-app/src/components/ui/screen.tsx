import { LinearGradient } from 'expo-linear-gradient';
import type { ReactNode } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  View,
  type ColorValue,
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
  backgroundGradient?: readonly [ColorValue, ColorValue, ...ColorValue[]];

  /** 스크롤 콘텐츠 위, SafeAreaView 안에 고정 렌더링된다. */
  header?: ReactNode;
  /** 스크롤 콘텐츠 아래, SafeAreaView 안에 고정 렌더링된다. */
  bottomBar?: ReactNode;

  avoidKeyboard?: boolean;
  edges?: Edge[];
  style?: StyleProp<ViewStyle>;
  contentContainerStyle?: StyleProp<ViewStyle>;
  keyboardShouldPersistTaps?: ScrollViewProps['keyboardShouldPersistTaps'];
};

export function Screen({
  children,
  scroll = false,
  backgroundColor,
  backgroundGradient,
  header,
  bottomBar,
  avoidKeyboard = false,
  edges = ['top', 'right', 'bottom', 'left'],
  style,
  contentContainerStyle,
  keyboardShouldPersistTaps = 'handled',
}: ScreenProps) {
  const theme = useTheme();
  const screenStyle = [
    styles.safeArea,
    { backgroundColor: backgroundGradient ? 'transparent' : backgroundColor ?? theme.background },
    style,
  ];

  const body = (
    <SafeAreaView style={screenStyle} edges={edges}>
      {header}
      {scroll ? (
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={[styles.content, contentContainerStyle]}
          keyboardShouldPersistTaps={keyboardShouldPersistTaps}
          showsVerticalScrollIndicator={false}
        >
          {children}
        </ScrollView>
      ) : (
        <View style={[styles.content, contentContainerStyle]}>{children}</View>
      )}
      {bottomBar}
    </SafeAreaView>
  );

  const background = backgroundGradient ? (
    <LinearGradient colors={backgroundGradient} style={styles.fill}>
      {body}
    </LinearGradient>
  ) : (
    body
  );

  if (!avoidKeyboard) {
    return background;
  }

  return (
    <KeyboardAvoidingView
      style={styles.fill}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      {background}
    </KeyboardAvoidingView>
  );
}
