import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    height: 220,
    width: '100%',
    backgroundColor: Palette.gray700,
    justifyContent: 'flex-end',
    alignItems: 'flex-end',
    overflow: 'hidden',
  },
  photo: {
    height: 220,
  },
  indicator: {
    margin: Spacing.sm + 4,
    backgroundColor: 'rgba(27, 27, 35, 0.6)',
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm + 2,
    paddingVertical: Spacing.xxs + 2,
  },
  indicatorText: {
    fontSize: 11,
    fontWeight: FontWeight.semibold,
    color: Palette.white,
  },
});
