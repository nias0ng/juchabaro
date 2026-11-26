import { StyleSheet } from 'react-native';

import { FontWeight, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    container: {
      paddingTop: Spacing.lg,
      paddingBottom: Spacing.md,
    },
    title: {
      fontWeight: FontWeight.bold,
      color: t.text.strong,
    },
    titleWithBack: {
      fontSize: 19,
      marginTop: -2,
    },
    titleWithoutBack: {
      fontSize: 21,
    },
    right: {
      marginLeft: 'auto',
    },
  });
