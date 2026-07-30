import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  saveLink: {
    fontSize: 12.5,
    fontWeight: FontWeight.bold,
    color: '#7a6ff0',
  },
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
