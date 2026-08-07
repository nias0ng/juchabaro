import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    gap: Spacing.sm + 2,
    width: '100%',
  },
  card: {
    flex: 1,
    gap: Spacing.xs,
    backgroundColor: Palette.white,
    borderRadius: Radius.lg,
    padding: Spacing.md,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.05,
    shadowRadius: 10,
    elevation: 2,
  },
  cardPressed: {
    opacity: 0.82,
  },
  label: {
    fontSize: 11,
    color: Palette.gray400,
  },
  value: {
    fontSize: 23,
    fontWeight: FontWeight.semibold,
    color: Palette.gray975,
  },
});
