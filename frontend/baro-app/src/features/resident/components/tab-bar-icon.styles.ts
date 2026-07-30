import { StyleSheet } from 'react-native';

import { FontWeight } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    gap: 4,
  },
  label: {
    fontSize: 10,
    lineHeight: 14,
    fontWeight: FontWeight.medium,
  },
  labelFocused: {
    fontWeight: FontWeight.bold,
  },
});
