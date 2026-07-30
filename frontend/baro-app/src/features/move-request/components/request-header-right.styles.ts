import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  badge: {
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm + 4,
    paddingVertical: Spacing.xs + 1,
  },
  manualBadge: {
    backgroundColor: Palette.sky100,
  },
  aiBadge: {
    backgroundColor: Palette.teal100,
  },
  badgeText: {
    fontSize: 10.5,
    fontWeight: FontWeight.bold,
  },
  manualText: {
    color: Palette.blue600,
  },
  aiText: {
    color: Palette.teal600,
  },
});
