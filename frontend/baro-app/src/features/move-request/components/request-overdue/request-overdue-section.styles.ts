import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    container: {
      flex: 1,
      alignItems: 'center',
      gap: Spacing.base + 2,
      paddingHorizontal: Spacing.lg,
      paddingTop: Spacing.md,
      paddingBottom: Spacing.xl,
    },
    textBlock: {
      alignItems: 'center',
      gap: Spacing.sm,
    },
    heading: {
      fontSize: 16,
      fontWeight: FontWeight.bold,
      color: t.text.strong,
      textAlign: 'center',
      lineHeight: 22.4,
    },
    pill: {
      backgroundColor: t.background.raised,
      borderRadius: Radius.full,
      paddingHorizontal: Spacing.sm + 4,
      paddingVertical: Spacing.xs + 1,
    },
    pillText: {
      fontSize: 10.5,
      fontWeight: FontWeight.bold,
      color: t.text.error,
    },
    detailButton: {
      width: '100%',
      marginTop: 'auto',
      backgroundColor: t.fill.inverse.strong,
      borderRadius: Radius.full,
      paddingVertical: Spacing.base + 3,
      alignItems: 'center',
    },
    detailButtonText: {
      fontSize: 14,
      fontWeight: FontWeight.bold,
      color: t.text.inverse,
    },
  });
