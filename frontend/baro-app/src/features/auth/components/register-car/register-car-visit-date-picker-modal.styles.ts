import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(20,22,28,0.45)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.lg,
  },
  sheet: {
    width: '100%',
    maxWidth: 360,
    borderRadius: Radius.xl,
    backgroundColor: Palette.white,
    padding: Spacing.lg,
  },
  title: {
    fontSize: 15,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
});
