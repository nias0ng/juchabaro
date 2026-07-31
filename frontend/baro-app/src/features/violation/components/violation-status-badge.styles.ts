import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  badge: {
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm + 2,
    paddingVertical: Spacing.xxs + 3,
  },
  text: {
    fontSize: 11,
    fontWeight: FontWeight.bold,
  },
  badgeUnresolved: {
    backgroundColor: '#fff0eb',
  },
  textUnresolved: {
    color: Palette.orange600,
  },
  badgeResolved: {
    backgroundColor: '#e9f7f2',
  },
  textResolved: {
    color: Palette.teal600,
  },
});
