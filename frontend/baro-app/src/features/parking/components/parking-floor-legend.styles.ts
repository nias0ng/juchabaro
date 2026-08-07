import { StyleSheet } from 'react-native';

import { Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    columnGap: Spacing.md - 4,
  },
  item: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.xs,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 3,
  },
  text: {
    fontSize: 10.5,
    color: '#7b8091',
  },
});

export const LEGEND_DOT_COLOR = {
  mine: Palette.yellow100,
  occupied: Palette.violet300,
  empty: Palette.lilac100,
} as const;
