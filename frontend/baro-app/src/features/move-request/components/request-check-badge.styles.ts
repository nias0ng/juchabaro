import { StyleSheet } from 'react-native';

import { type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    outer: {
      backgroundColor: t.background.raised,
      alignItems: 'center',
      justifyContent: 'center',
      shadowColor: t.shadow,
      shadowOffset: { width: 0, height: 12 },
      shadowOpacity: 0.08,
      shadowRadius: 15,
      elevation: 4,
    },
    inner: {
      alignItems: 'center',
      justifyContent: 'center',
    },
    check: {
      color: t.overlay.onMediaText,
    },
  });
