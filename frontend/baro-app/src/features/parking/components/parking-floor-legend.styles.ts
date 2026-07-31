import { StyleSheet } from 'react-native';

import { Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    columnGap: Spacing.md - 4,
    rowGap: Spacing.xs,
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
  occupied: Palette.lilac200,
  empty: Palette.lilac100,
  ev: Palette.teal100,
  disabled: Palette.sky100,
  violation: Palette.peach100,
} as const;
