import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  summaryCard: {
    width: '100%',
    borderRadius: 22,
    padding: 16,
    gap: Spacing.sm,
    alignItems: 'flex-start',
  },
  summaryBadge: {
    backgroundColor: 'rgba(255,255,255,0.75)',
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  summaryBadgeText: {
    fontSize: 9.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  summaryPlate: {
    fontSize: 24,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    letterSpacing: 0.4,
  },
  sectionLabel: {
    fontSize: 12,
    fontWeight: FontWeight.bold,
    color: Palette.gray600,
  },
  cameraIcon: {
    fontSize: 12,
  },
});
