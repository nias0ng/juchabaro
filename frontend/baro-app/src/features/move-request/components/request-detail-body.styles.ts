import { StyleSheet } from 'react-native';

import { Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    statusContainer: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      paddingVertical: Spacing.xxl,
      paddingHorizontal: Spacing.lg,
    },
    statusText: {
      fontSize: 13.5,
      color: t.text.weaker,
      textAlign: 'center',
    },
  });
