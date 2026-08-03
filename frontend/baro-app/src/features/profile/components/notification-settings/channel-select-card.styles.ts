import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Shadows, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  card: {
    width: '100%',
    gap: Spacing.base,
    backgroundColor: Palette.white,
    borderRadius: 26,
    padding: Spacing.md + 4,
    ...Shadows.card,
  },
  title: {
    fontSize: 14.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  row: {
    flexDirection: 'row',
    gap: Spacing.sm + 2,
  },
  option: {
    flex: 1,
    height: 46,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: Spacing.md,
    backgroundColor: '#f5f4fb',
  },
  optionSelected: {
    backgroundColor: Palette.gray975,
  },
  optionLabel: {
    fontSize: 13,
    fontWeight: FontWeight.bold,
    color: Palette.gray600,
  },
  optionLabelSelected: {
    color: Palette.white,
  },
});
