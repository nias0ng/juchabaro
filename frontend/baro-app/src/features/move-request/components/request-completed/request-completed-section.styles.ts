import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    gap: Spacing.base + 2,
    paddingHorizontal: Spacing.lg,
    paddingTop: Spacing.xl,
    paddingBottom: Spacing.xl,
  },
  textBlock: {
    alignItems: 'center',
    gap: Spacing.sm,
  },
  heading: {
    fontSize: 20,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    textAlign: 'center',
    lineHeight: 27,
  },
  subheading: {
    fontSize: 12.5,
    color: '#7b8091',
    textAlign: 'center',
    lineHeight: 21.25,
  },
  homeButton: {
    width: '100%',
    marginTop: 'auto',
    backgroundColor: Palette.gray975,
    borderRadius: Radius.full,
    paddingVertical: Spacing.base + 3,
    alignItems: 'center',
  },
  homeButtonText: {
    fontSize: 14,
    fontWeight: FontWeight.bold,
    color: Palette.white,
  },
});
