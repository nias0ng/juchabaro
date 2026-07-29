import { StyleSheet } from 'react-native';

import { Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
  },
  track: {
    flex: 1,
    height: 5,
    borderRadius: 3,
    backgroundColor: Palette.violet100,
  },
  trackActive: {
    backgroundColor: Palette.violet500,
  },
  label: {
    fontSize: 11,
    color: Palette.gray500,
  },
});
