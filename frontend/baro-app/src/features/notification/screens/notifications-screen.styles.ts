import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: Spacing.xs,
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  markAllText: {
    fontSize: 12.5,
    color: Palette.violet500,
  },
  statusContainer: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: Spacing.xxl,
  },
  statusText: {
    fontSize: 13.5,
    color: Palette.gray500,
    textAlign: 'center',
  },
});
