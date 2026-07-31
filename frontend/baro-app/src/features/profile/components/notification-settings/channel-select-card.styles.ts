import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  card: {
    width: '100%',
    gap: Spacing.base,
    backgroundColor: Palette.white,
    borderRadius: 26,
    padding: Spacing.md + 4,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.06,
    shadowRadius: 13,
    elevation: 2,
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
