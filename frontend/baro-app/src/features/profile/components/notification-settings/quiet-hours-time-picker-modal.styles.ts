import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

// columns와 column이 같은 높이를 공유해야 ScrollView가 이 높이만큼만 잘려서 스크롤이 가능해진다.
const COLUMN_HEIGHT = 220;

export const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(20,22,28,0.45)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.lg,
  },
  sheet: {
    width: '100%',
    maxWidth: 320,
    borderRadius: Radius.xl,
    backgroundColor: Palette.white,
    padding: Spacing.lg,
  },
  title: {
    fontSize: 15,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    textAlign: 'center',
  },
  columns: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.sm,
    height: COLUMN_HEIGHT,
  },
  column: {
    flex: 1,
    maxWidth: 80,
    // alignItems: 'center'인 부모 안에서는 stretch가 적용되지 않아 높이를 직접 지정해야
    // ScrollView가 이 크기로 잘리고(스크롤 가능), 내용이 위아래 문구와 겹치지 않는다.
    height: COLUMN_HEIGHT,
  },
  colon: {
    fontSize: 18,
    fontWeight: FontWeight.bold,
    color: Palette.gray400,
  },
  item: {
    alignItems: 'center',
    paddingVertical: Spacing.sm + 2,
    borderRadius: Radius.md,
  },
  itemSelected: {
    backgroundColor: Palette.violet100,
  },
  itemText: {
    fontSize: 16,
    color: Palette.gray500,
  },
  itemTextSelected: {
    fontWeight: FontWeight.bold,
    color: Palette.violet600,
  },
  flexButton: {
    flex: 1,
  },
});
