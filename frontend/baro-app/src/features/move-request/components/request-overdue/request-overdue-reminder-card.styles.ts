import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  card: {
    width: '100%',
    backgroundColor: '#fff8ec',
    borderRadius: Radius.input,
    paddingHorizontal: Spacing.base,
    paddingVertical: Spacing.sm + 2,
    gap: Spacing.xxs + 2,
  },
  label: {
    fontSize: 11,
    fontWeight: FontWeight.bold,
    color: '#a35b3d',
  },
  countdown: {
    fontSize: 26,
    fontWeight: FontWeight.semibold,
    color: '#a35b3d',
  },
});
