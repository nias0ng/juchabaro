import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    gap: Spacing.sm,
    paddingBottom: Spacing.base,
  },
  action: {
    flex: 1,
    borderRadius: Radius.input,
    paddingHorizontal: Spacing.sm,
    paddingVertical: Spacing.base,
    gap: Spacing.md,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.04,
    shadowRadius: 8,
    elevation: 1,
  },
  label: {
    fontSize: 12,
    lineHeight: 15,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  icon: {
    width: 22,
    height: 22,
    borderRadius: 7,
  },
});
