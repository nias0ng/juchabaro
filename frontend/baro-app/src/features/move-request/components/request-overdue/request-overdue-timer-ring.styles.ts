import { StyleSheet } from 'react-native';

import { FontWeight, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    wrapper: {
      width: 150,
      height: 150,
      alignItems: 'center',
      justifyContent: 'center',
    },
    spinner: {
      position: 'absolute',
      width: 150,
      height: 150,
    },
    dial: {
      width: 124,
      height: 124,
      borderRadius: 62,
      backgroundColor: t.background.raised,
      alignItems: 'center',
      justifyContent: 'center',
      shadowColor: t.shadow,
      shadowOffset: { width: 0, height: 8 },
      shadowOpacity: 0.06,
      shadowRadius: 12,
      elevation: 3,
    },
    time: {
      fontSize: 26,
      fontWeight: FontWeight.semibold,
      color: t.text.error,
    },
    caption: {
      fontSize: 9.5,
      color: t.text.weaker,
    },
  });
