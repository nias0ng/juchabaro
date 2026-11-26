import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    container: {
      width: '100%',
      maxWidth: 354,
      gap: Spacing.md - 2,
      backgroundColor: t.background.raised,
      borderRadius: Radius.xl + 4,
      padding: Spacing.lg - 2,
      shadowColor: t.shadow,
      shadowOffset: { width: 0, height: 12 },
      shadowOpacity: 0.07,
      shadowRadius: 15,
      elevation: 3,
    },
    row: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    label: {
      fontSize: 13,
      color: t.text.weaker,
    },
    value: {
      fontSize: 13,
      fontWeight: FontWeight.bold,
      color: t.text.strong,
    },
    divider: {
      height: 1,
      backgroundColor: t.fill.neutral.weak,
    },
    statusRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: Spacing.sm + 2,
    },
    statusDot: {
      width: 8,
      height: 8,
      borderRadius: 4,
      backgroundColor: t.fill.success.strong,
    },
    statusText: {
      flex: 1,
      fontSize: 12.5,
      fontWeight: FontWeight.bold,
      color: t.text.success,
    },
    statusTime: {
      fontSize: 12,
      color: t.text.weaker,
    },
  });
