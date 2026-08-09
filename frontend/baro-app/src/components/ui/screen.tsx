import { LinearGradient } from 'expo-linear-gradient';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  RefreshControl,
  ScrollView,
  TextInput,
  View,
  type ColorValue,
  type ScrollViewProps,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView, type Edge } from 'react-native-safe-area-context';

import { useTheme } from '@/hooks/use-theme';
import { Spacing } from '@/styles';

import { styles } from './screen.styles';

const KEYBOARD_EXTRA_SPACE = Spacing.xxxl;

type ScreenProps = {
  children: ReactNode;
  scroll?: boolean;
  backgroundColor?: string;
  backgroundGradient?: readonly [ColorValue, ColorValue, ...ColorValue[]];
  /** backgroundGradient와 길이가 같아야 한다. 지정하지 않으면 0~1 구간에 고르게 퍼진다. */
  backgroundGradientLocations?: readonly [number, number, ...number[]];

  /** 스크롤 콘텐츠 위, SafeAreaView 안에 고정 렌더링된다. */
  header?: ReactNode;
  /** 스크롤 콘텐츠 아래, SafeAreaView 안에 고정 렌더링된다. */
  bottomBar?: ReactNode;

  avoidKeyboard?: boolean;
  edges?: Edge[];
  style?: StyleProp<ViewStyle>;
  contentContainerStyle?: StyleProp<ViewStyle>;
  keyboardShouldPersistTaps?: ScrollViewProps['keyboardShouldPersistTaps'];
  refreshing?: boolean;
  onRefresh?: () => void;
};

export function Screen({
  children,
  scroll = false,
  backgroundColor,
  backgroundGradient,
  backgroundGradientLocations,
  header,
  bottomBar,
  avoidKeyboard = false,
  edges = ['top', 'right', 'bottom', 'left'],
  style,
  contentContainerStyle,
  keyboardShouldPersistTaps = 'handled',
  refreshing = false,
  onRefresh,
}: ScreenProps) {
  const theme = useTheme();
  const [keyboardHeight, setKeyboardHeight] = useState(0);
  const scrollViewRef = useRef<ScrollView>(null);

  useEffect(() => {
    if (!avoidKeyboard || Platform.OS !== 'android') return;

    const showSubscription = Keyboard.addListener('keyboardDidShow', (event) => {
      setKeyboardHeight(event.endCoordinates.height);
    });
    const hideSubscription = Keyboard.addListener('keyboardDidHide', () => {
      setKeyboardHeight(0);
    });

    return () => {
      showSubscription.remove();
      hideSubscription.remove();
    };
  }, [avoidKeyboard]);

  // KeyboardAvoidingView/패딩은 화면 전체만 밀어 올릴 뿐, 포커스된 입력창이 실제로
  // 보이는 위치까지 스크롤해 주지는 않는다. 폼이 길면 입력창이 키보드 뒤에 가려진 채로
  // 남아 입력해도 안 보이는 문제가 생겨서, 포커스된 입력창까지 직접 스크롤시킨다.
  useEffect(() => {
    if (!avoidKeyboard || !scroll) return;

    const showSubscription = Keyboard.addListener('keyboardDidShow', () => {
      const focusedInput = TextInput.State.currentlyFocusedInput();
      if (focusedInput) {
        scrollViewRef.current?.scrollResponderScrollNativeHandleToKeyboard(
          focusedInput,
          KEYBOARD_EXTRA_SPACE,
          true,
        );
      }
    });

    return () => showSubscription.remove();
  }, [avoidKeyboard, scroll]);

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
          ref={scrollViewRef}
          style={styles.scroll}
          contentContainerStyle={[
            styles.content,
            contentContainerStyle,
            keyboardHeight > 0 && { paddingBottom: keyboardHeight + KEYBOARD_EXTRA_SPACE },
          ]}
          keyboardShouldPersistTaps={keyboardShouldPersistTaps}
          keyboardDismissMode={
            avoidKeyboard ? (Platform.OS === 'ios' ? 'interactive' : 'on-drag') : undefined
          }
          showsVerticalScrollIndicator={false}
          refreshControl={
            onRefresh ? <RefreshControl refreshing={refreshing} onRefresh={onRefresh} /> : undefined
          }
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
    <LinearGradient colors={backgroundGradient} locations={backgroundGradientLocations} style={styles.fill}>
      {body}
    </LinearGradient>
  ) : (
    body
  );

  if (!avoidKeyboard || Platform.OS !== 'ios') {
    return background;
  }

  return (
    <KeyboardAvoidingView style={styles.fill} behavior="padding">
      {background}
    </KeyboardAvoidingView>
  );
}
