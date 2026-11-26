import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    row: {
      width: '100%',
      flexDirection: 'row',
      alignItems: 'center',
      gap: Spacing.sm + 2,
      backgroundColor: t.background.raised,
      borderRadius: Radius.input,
      paddingHorizontal: Spacing.md,
      paddingVertical: Spacing.base + 1,
      shadowColor: t.shadow,
      shadowOffset: { width: 0, height: 6 },
      shadowOpacity: 0.05,
      shadowRadius: 9,
      elevation: 2,
    },
    radioOuter: {
      width: 14,
      height: 14,
      borderRadius: 7,
      borderWidth: 2,
      borderColor: t.stroke.success,
    },
    zoneText: {
      flex: 1,
      fontSize: 13.5,
      fontWeight: FontWeight.bold,
      color: t.text.strong,
    },
    zoneTextPlaceholder: {
      fontWeight: FontWeight.regular,
      color: t.text.weaker,
    },
    selectText: {
      fontSize: 12.5,
      color: t.text.brand,
    },
  });
