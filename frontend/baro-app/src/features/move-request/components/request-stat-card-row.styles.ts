import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  row: {
    width: '100%',
    flexDirection: 'row',
    gap: Spacing.sm,
  },
  card: {
    flex: 1,
    backgroundColor: Palette.white,
    borderRadius: Radius.lg,
    padding: Spacing.base,
    gap: Spacing.xxs,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.05,
    shadowRadius: 9,
    elevation: 2,
  },
  label: {
    fontSize: 9.5,
    color: '#9599a7',
  },
  value: {
    fontSize: 13.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
});
