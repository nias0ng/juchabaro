import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.base,
    width: '100%',
  },
  rowPressed: {
    opacity: 0.65,
  },
  iconOuter: {
    width: 40,
    height: 40,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconInner: {
    width: 16,
    height: 16,
    borderRadius: 5,
  },
  content: {
    flex: 1,
    gap: Spacing.xxs,
  },
  title: {
    fontSize: 14,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  meta: {
    fontSize: 11.5,
    color: '#9599a7',
  },
  statusDescription: {
    fontSize: 11.5,
    color: '#9599a7',
  },
});
