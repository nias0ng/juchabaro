import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

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
