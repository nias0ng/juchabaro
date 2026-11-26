import { StyleSheet } from 'react-native';

import { Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    field: {
      width: '100%',
      minHeight: 90,
      backgroundColor: t.background.raised,
      borderRadius: Radius.input,
      paddingHorizontal: Spacing.md,
      paddingVertical: Spacing.base + 2,
      fontSize: 13,
      lineHeight: 22.1,
      color: t.text.strong,
      shadowColor: t.shadow,
      shadowOffset: { width: 0, height: 6 },
      shadowOpacity: 0.05,
      shadowRadius: 9,
      elevation: 2,
    },
  });
