import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    width: '100%',
    maxWidth: 354,
    gap: Spacing.md - 2,
    backgroundColor: Palette.white,
    borderRadius: Radius.xl + 4,
    padding: Spacing.lg - 2,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.07,
    shadowRadius: 15,
    elevation: 3,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  label: {
    fontSize: 13,
    color: Palette.gray400,
  },
  value: {
    fontSize: 13,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  divider: {
    height: 1,
    backgroundColor: Palette.gray100,
  },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm + 2,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: Palette.emerald500,
  },
  statusText: {
    flex: 1,
    fontSize: 12.5,
    fontWeight: FontWeight.bold,
    color: Palette.emerald500,
  },
  statusTime: {
    fontSize: 12,
    color: Palette.gray400,
  },
});
