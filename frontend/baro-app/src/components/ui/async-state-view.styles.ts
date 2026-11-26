import { StyleSheet } from 'react-native';

import { Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    container: {
      alignItems: 'center',
      justifyContent: 'center',
      paddingVertical: Spacing.xxl,
    },
    fill: {
      flex: 1,
    },
    text: {
      fontSize: 13.5,
      color: t.text.weaker,
      textAlign: 'center',
    },
  });
