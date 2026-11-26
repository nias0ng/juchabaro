import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    container: {
      flex: 1,
      alignItems: 'center',
      gap: Spacing.base,
      paddingHorizontal: Spacing.lg,
      paddingTop: Spacing.md,
      paddingBottom: Spacing.xl,
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
      color: t.text.warning,
    },
    description: {
      fontSize: 12.5,
      color: t.text.weaker,
      textAlign: 'center',
      lineHeight: 20,
    },
  });
