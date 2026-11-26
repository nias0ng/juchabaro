import { StyleSheet } from 'react-native';

import { Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    container: {
      borderWidth: 1,
      borderStyle: 'dashed',
      borderColor: t.stroke.error,
      backgroundColor: t.fill.warning.weak,
      borderRadius: Radius.lg,
      paddingHorizontal: Spacing.md - 1,
      paddingVertical: Spacing.sm + 3,
      gap: Spacing.xxs,
    },
    containerDanger: {
      borderColor: t.stroke.error,
      backgroundColor: t.fill.error.weak,
    },
    text: {
      fontSize: 13,
      lineHeight: 17.5,
      textAlign: 'center',
      color: t.text.warning,
    },
    textDanger: {
      color: t.text.strong,
    },
  });
