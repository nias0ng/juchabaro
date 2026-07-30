import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  pill: {
    width: '100%',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Palette.white80,
    borderRadius: Radius.full,
    paddingVertical: Spacing.md - 2,
  },
  text: {
    fontSize: 14,
    fontWeight: FontWeight.medium,
    color: Palette.gray600,
    textAlign: 'center',
  },
});
