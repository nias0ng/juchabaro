import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Shadows, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  // Swipeable은 스와이프 액션을 숨기려고 내부 컨테이너에 overflow: hidden을 건다. 그림자를
  // Swipeable 안쪽(container)에 두면 둥근 모서리 밖으로 퍼지는 부분이 사각형으로 잘려나가서,
  // Swipeable을 감싸는 이 바깥 wrapper에 그림자를 옮겨뒀다. borderRadius도 같이 맞춰야
  // 안드로이드의 elevation 그림자가 둥근 모양을 따라간다.
  shadowWrapper: {
    width: '100%',
    borderRadius: Radius.xl,
    ...Shadows.card,
  },
  container: {
    flexDirection: 'row',
    gap: Spacing.md - 2,
    alignItems: 'flex-start',
    width: '100%',
    backgroundColor: Palette.white,
    borderRadius: Radius.xl,
    padding: Spacing.md + 2,
  },
  iconOuter: {
    width: 42,
    height: 42,
    borderRadius: 15,
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconInner: {
    width: 16,
    height: 16,
    borderRadius: 5,
  },
  content: {
    flex: 1,
    gap: Spacing.xs,
  },
  title: {
    fontSize: 14.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  body: {
    fontSize: 12.5,
    lineHeight: 20,
    color: Palette.gray500,
  },
  meta: {
    fontSize: 11,
    color: Palette.gray400,
  },
  deleteAction: {
    width: 72,
    marginLeft: Spacing.sm,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Palette.red500,
    borderRadius: Radius.xl,
  },
  deleteActionText: {
    fontSize: 13,
    fontWeight: FontWeight.bold,
    color: Palette.white,
  },
});
