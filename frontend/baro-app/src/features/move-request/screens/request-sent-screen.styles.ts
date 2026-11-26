import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    content: {
      flexGrow: 1,
      width: '100%',
      alignItems: 'center',
      paddingTop: Spacing.xl + 20,
      paddingBottom: Spacing.lg,
      gap: Spacing.md,
    },
    title: {
      fontSize: 25,
      fontWeight: FontWeight.bold,
      color: t.text.strong,
      textAlign: 'center',
      letterSpacing: -0.4,
      marginTop: Spacing.lg,
    },
    subtitle: {
      fontSize: 13.5,
      lineHeight: 23.63,
      color: t.text.weaker,
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
      backgroundColor: t.fill.inverse.strong,
      alignItems: 'center',
      justifyContent: 'center',
    },
    primaryButtonText: {
      fontSize: 15,
      fontWeight: FontWeight.bold,
      color: t.text.inverse,
    },
    secondaryButton: {
      width: '100%',
      height: 48,
      borderRadius: Radius.full,
      backgroundColor: t.overlay.glass,
      alignItems: 'center',
      justifyContent: 'center',
    },
    secondaryButtonText: {
      fontSize: 14,
      fontWeight: FontWeight.medium,
      color: t.text.weak,
    },
  });
