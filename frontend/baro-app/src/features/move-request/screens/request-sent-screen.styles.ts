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
  iconOuter: {
    width: 96,
    height: 96,
    borderRadius: 48,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Palette.white,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 14 },
    shadowOpacity: 0.09,
    shadowRadius: 17,
    elevation: 4,
  },
  iconInner: {
    width: 38,
    height: 38,
    borderRadius: 14,
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
  noticeBox: {
    width: '100%',
    maxWidth: 346,
    backgroundColor: Palette.white72,
    borderRadius: Radius.xl - 4,
    paddingHorizontal: Spacing.md + 2,
    paddingVertical: Spacing.md,
  },
  noticeText: {
    fontSize: 12,
    lineHeight: 21,
    color: '#5c6070',
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
