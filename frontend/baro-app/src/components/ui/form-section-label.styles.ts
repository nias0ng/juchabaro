import { StyleSheet } from 'react-native';

import { FontWeight, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    label: {
      fontSize: 13,
      fontWeight: FontWeight.bold,
      color: t.text.strong,
    },
    labelMuted: {
      fontSize: 12,
      color: t.text.weak,
    },
    suffix: {
      fontWeight: FontWeight.regular,
      color: t.text.weaker,
    },
    suffixMuted: {
      fontSize: 12,
    },
  });
