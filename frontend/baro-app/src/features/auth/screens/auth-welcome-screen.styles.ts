import { StyleSheet } from 'react-native';

import { ContentWidth, FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  gradient: {
    flex: 1,
  },
  safeArea: {
    flex: 1,
  },
  content: {
    flex: 1,
    width: '100%',
    maxWidth: ContentWidth.compact,
    alignSelf: 'center',
    justifyContent: 'center',
    paddingHorizontal: Spacing.lg,
  },
  logoBadge: {
    width: 96,
    height: 96,
    borderRadius: 30,
    backgroundColor: Palette.white,
    alignSelf: 'center',
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.md,
    shadowColor: '#14161c',
    shadowOffset: { width: 0, height: 14 },
    shadowOpacity: 0.1,
    shadowRadius: 34,
    elevation: 6,
  },
  logo: {
    width: '100%',
    height: '100%',
  },
  brand: {
    fontSize: 26,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    letterSpacing: -0.4,
    textAlign: 'center',
  },
  tagline: {
    fontSize: 13,
    color: Palette.gray600,
    textAlign: 'center',
  },
  buttonGroup: {
    alignSelf: 'stretch',
    paddingTop: Spacing.lg,
  },
  footer: {
    paddingBottom: Spacing.xl,
    fontSize: 11,
    color: Palette.gray500,
    textAlign: 'center',
  },
});
