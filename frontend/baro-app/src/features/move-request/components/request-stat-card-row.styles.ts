import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    row: {
      width: '100%',
      flexDirection: 'row',
      gap: Spacing.sm,
    },
    card: {
      flex: 1,
      backgroundColor: t.background.raised,
      borderRadius: Radius.lg,
      padding: Spacing.base,
      gap: Spacing.xxs,
      shadowColor: t.shadow,
      shadowOffset: { width: 0, height: 6 },
      shadowOpacity: 0.05,
      shadowRadius: 9,
      elevation: 2,
    },
    label: {
      fontSize: 9.5,
      color: t.text.weaker,
    },
    value: {
      fontSize: 13.5,
      fontWeight: FontWeight.bold,
      color: t.text.strong,
    },
  });
