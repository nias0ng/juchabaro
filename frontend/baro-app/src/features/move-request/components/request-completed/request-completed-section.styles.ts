import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
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
      color: t.text.strong,
      textAlign: 'center',
      lineHeight: 27,
    },
    subheading: {
      fontSize: 12.5,
      color: t.text.weaker,
      textAlign: 'center',
      lineHeight: 21.25,
    },
    pill: {
      marginTop: Spacing.xxs,
      backgroundColor: t.background.raised,
      borderRadius: Radius.full,
      paddingHorizontal: Spacing.sm + 4,
      paddingVertical: Spacing.xs + 1,
    },
    pillText: {
      fontSize: 10.5,
      fontWeight: FontWeight.bold,
      color: t.text.brand,
    },
    homeButton: {
      width: '100%',
      marginTop: 'auto',
      backgroundColor: t.fill.inverse.strong,
      borderRadius: Radius.full,
      paddingVertical: Spacing.base + 3,
      alignItems: 'center',
    },
    homeButtonText: {
      fontSize: 14,
      fontWeight: FontWeight.bold,
      color: t.text.inverse,
    },
  });
