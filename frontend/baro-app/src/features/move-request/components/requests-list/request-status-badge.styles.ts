import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  badge: {
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm + 3,
    paddingVertical: Spacing.xxs + 3,
  },
  text: {
    fontSize: 11,
    fontWeight: FontWeight.bold,
  },
  badgeResponded: {
    backgroundColor: '#ede9fd',
  },
  textResponded: {
    color: '#5c4fe0',
  },
  badgePending: {
    backgroundColor: '#fff0eb',
  },
  textPending: {
    color: Palette.orange600,
  },
  badgeClosed: {
    backgroundColor: Palette.sky100,
  },
  textClosed: {
    color: Palette.blue600,
  },
});
