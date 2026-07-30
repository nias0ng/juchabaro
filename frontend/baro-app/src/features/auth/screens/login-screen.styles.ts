import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  header: {
    paddingTop: Spacing.lg,
  },
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
