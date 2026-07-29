import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  heading: {
    fontSize: 24,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    letterSpacing: -0.4,
  },
  subheading: {
    fontSize: 13.5,
    color: Palette.gray500,
  },
  formError: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: Spacing.sm,
    borderRadius: Radius.lg,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.base,
    marginTop: -(Spacing.xl - Spacing.base),
  },
  formErrorIcon: {
    fontSize: 12,
  },
  formErrorText: {
    flex: 1,
    fontSize: 12,
  },
  footerRow: {
    alignItems: 'center',
  },
  footerText: {
    fontSize: 13,
    color: Palette.gray400,
  },
  footerLink: {
    fontSize: 13,
    fontWeight: FontWeight.bold,
    color: Palette.violet600,
  },
});
