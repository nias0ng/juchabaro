import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  heading: {
    fontSize: 20,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    lineHeight: 27,
  },
  description: {
    fontSize: 12,
    color: Palette.gray500,
  },
  summaryCard: {
    width: '100%',
    borderRadius: 22,
    padding: 18,
    gap: Spacing.sm,
    alignItems: 'flex-start',
  },
  badge: {
    backgroundColor: 'rgba(255,255,255,0.75)',
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  badgeText: {
    fontSize: 9.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  plate: {
    fontSize: 26,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    letterSpacing: 0.4,
  },
  divider: {
    height: 1,
    width: '100%',
    backgroundColor: 'rgba(255,255,255,0.6)',
  },
  sectionTitle: {
    fontSize: 11,
    fontWeight: FontWeight.bold,
    color: Palette.gray600,
  },
  summaryRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
  },
  summaryRowLabel: {
    fontSize: 12,
    color: Palette.gray600,
  },
  summaryRowValue: {
    fontSize: 12,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
});
