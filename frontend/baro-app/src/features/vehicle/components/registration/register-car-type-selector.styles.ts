import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    gap: Spacing.sm,
    width: '100%',
  },
  tab: {
    flex: 1,
    height: 42,
    borderRadius: 14,
    backgroundColor: Palette.white,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tabSelected: {
    backgroundColor: Palette.gray975,
  },
  tabLabel: {
    fontSize: 12.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray600,
  },
  tabLabelSelected: {
    color: Palette.white,
  },
});
