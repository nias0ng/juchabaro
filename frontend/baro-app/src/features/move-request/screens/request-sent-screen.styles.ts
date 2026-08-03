import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  content: {
    flexGrow: 1,
    width: '100%',
    alignItems: 'center',
    paddingHorizontal: Spacing.lg + 2,
    paddingTop: Spacing.xl + 20,
    paddingBottom: Spacing.lg,
    gap: Spacing.md,
  },
  title: {
    fontSize: 25,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    textAlign: 'center',
    letterSpacing: -0.4,
    marginTop: Spacing.lg,
  },
  subtitle: {
    fontSize: 13.5,
    lineHeight: 23.63,
    color: Palette.gray500,
    textAlign: 'center',
  },
  summaryMargin: {
    width: '100%',
    alignItems: 'center',
    marginTop: Spacing.xs,
  },
  actions: {
    width: '100%',
    marginTop: 'auto',
    gap: Spacing.sm + 2,
  },
  primaryButton: {
    width: '100%',
    height: 56,
    borderRadius: Radius.full,
    backgroundColor: Palette.gray975,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryButtonText: {
    fontSize: 15,
    fontWeight: FontWeight.bold,
    color: Palette.white,
  },
  secondaryButton: {
    width: '100%',
    height: 48,
    borderRadius: Radius.full,
    backgroundColor: 'rgba(255, 255, 255, 0.85)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  secondaryButtonText: {
    fontSize: 14,
    fontWeight: FontWeight.medium,
    color: '#5c6070',
  },
});
