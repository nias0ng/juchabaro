import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  card: {
    width: '100%',
    gap: Spacing.sm + 2,
    backgroundColor: Palette.white,
    borderRadius: Radius.xl,
    padding: Spacing.md + 4,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.05,
    shadowRadius: 10,
    elevation: 2,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
  },
  dot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  dotActive: {
    backgroundColor: '#7a6ff0',
  },
  dotDone: {
    backgroundColor: '#c9c4e8',
  },
  dotNext: {
    backgroundColor: '#e2e0ec',
  },
  divider: {
    height: 1,
    width: '100%',
    backgroundColor: '#f2f0fa',
  },
  labelActive: {
    fontSize: 12.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  valueActive: {
    marginLeft: 'auto',
    fontSize: 12.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  label: {
    fontSize: 12,
    color: Palette.gray500,
  },
  value: {
    marginLeft: 'auto',
    fontSize: 12,
    color: '#9599a7',
  },
  nextBadge: {
    marginLeft: 'auto',
    backgroundColor: '#ede9fd',
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm,
    paddingVertical: 3,
  },
  nextBadgeText: {
    fontSize: 10,
    fontWeight: FontWeight.semibold,
    color: '#5c4fe0',
  },
});
