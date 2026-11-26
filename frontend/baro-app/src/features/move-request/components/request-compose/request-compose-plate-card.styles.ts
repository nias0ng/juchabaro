import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    card: {
      width: '100%',
      backgroundColor: t.background.raised,
      borderRadius: Radius.input - 2,
      paddingHorizontal: Spacing.base + 3,
      paddingVertical: Spacing.base + 1,
    },
    cardError: {
      borderWidth: 1,
      borderColor: t.stroke.error,
    },
    plateText: {
      fontSize: 14,
      fontWeight: FontWeight.bold,
      color: t.text.strong,
      backgroundColor: 'transparent',
      borderWidth: 0,
      padding: 0,
    },
    errorText: {
      marginTop: Spacing.xs,
      fontSize: 11.5,
      color: t.text.error,
    },
  });
