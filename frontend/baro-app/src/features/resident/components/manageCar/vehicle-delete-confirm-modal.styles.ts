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
    fontSize: 17,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  plate: {
    fontSize: 20,
    fontWeight: FontWeight.bold,
    color: Palette.gray700,
    letterSpacing: 0.4,
  },
  description: {
    fontSize: 12,
    color: Palette.gray500,
  },
  errorBanner: {
    borderRadius: Radius.md,
    paddingHorizontal: Spacing.base,
    paddingVertical: Spacing.sm,
  },
  errorText: {
    fontSize: 12,
  },
  actionItem: {
    flex: 1,
  },
});
