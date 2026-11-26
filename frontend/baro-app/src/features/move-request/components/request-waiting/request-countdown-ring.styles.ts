import { StyleSheet } from 'react-native';

import { FontWeight, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    ring: {
      width: 170,
      height: 170,
      marginTop: Spacing.lg,
      alignItems: 'center',
      justifyContent: 'center',
    },
    svg: {
      position: 'absolute',
    },
    dial: {
      width: 142,
      height: 142,
      borderRadius: 71,
      backgroundColor: t.background.raised,
      alignItems: 'center',
      justifyContent: 'center',
      gap: 2,
    },
    time: {
      fontSize: 32,
      fontWeight: FontWeight.semibold,
      color: t.text.strong,
      letterSpacing: -0.5,
    },
    caption: {
      fontSize: 10,
      color: t.text.weaker,
      letterSpacing: 1,
    },
  });
