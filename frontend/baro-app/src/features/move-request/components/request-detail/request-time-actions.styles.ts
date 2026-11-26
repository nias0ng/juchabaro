import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    container: {
      marginTop: Spacing.sm,
      gap: Spacing.base + 2,
    },
    containerDisabled: {
      opacity: 0.5,
    },
    heading: {
      fontSize: 14,
      fontWeight: FontWeight.bold,
      color: t.text.weak,
    },
    immediateButton: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: Spacing.sm,
      backgroundColor: t.fill.inverse.strong,
      borderRadius: Radius.lg,
      paddingVertical: Spacing.md + 2,
      paddingHorizontal: Spacing.lg,
    },
    immediateButtonText: {
      fontSize: 17,
      fontWeight: FontWeight.bold,
      color: t.text.inverse,
    },
    immediateButtonArrow: {
      fontSize: 17,
      fontWeight: FontWeight.bold,
      color: t.text.inverse,
    },
    timedRow: {
      flexDirection: 'row',
      gap: Spacing.sm + 2,
    },
    timedButton30: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: t.fill.brand.weak,
      borderRadius: Radius.lg,
      paddingVertical: Spacing.md,
    },
    timedButton30Text: {
      fontSize: 16,
      fontWeight: FontWeight.bold,
      color: t.text.brand,
    },
    timedButton60: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: t.fill.success.weak,
      borderRadius: Radius.lg,
      paddingVertical: Spacing.md,
    },
    timedButton60Text: {
      fontSize: 16,
      fontWeight: FontWeight.bold,
      color: t.text.success,
    },
    declineLink: {
      alignItems: 'center',
      paddingVertical: Spacing.xs,
    },
    declineText: {
      fontSize: 14,
      fontWeight: FontWeight.bold,
      color: t.text.error,
      textDecorationLine: 'underline',
    },
  });
