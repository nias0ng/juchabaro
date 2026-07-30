import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    width: '100%',
    alignItems: 'center',
    paddingTop: Spacing.xxl,
  },
  iconCircle: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: Palette.white,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 14 },
    shadowOpacity: 0.09,
    shadowRadius: 17,
    elevation: 4,
  },
  iconGradient: {
    width: 34,
    height: 34,
    borderRadius: 12,
  },
  heading: {
    fontSize: 22,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    letterSpacing: -0.3,
    textAlign: 'center',
    paddingTop: Spacing.lg,
  },
  description: {
    fontSize: 13,
    color: Palette.gray500,
    textAlign: 'center',
    lineHeight: 22.75,
    paddingTop: Spacing.sm,
  },
  actions: {
    width: '100%',
    paddingTop: Spacing.xxl,
  },
});
