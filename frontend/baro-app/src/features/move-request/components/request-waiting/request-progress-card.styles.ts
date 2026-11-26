import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    card: {
      width: '100%',
      gap: Spacing.sm + 2,
      backgroundColor: t.background.raised,
      borderRadius: Radius.xl,
      padding: Spacing.md + 4,
      shadowColor: t.shadow,
      shadowOffset: { width: 0, height: 8 },
      shadowOpacity: 0.05,
      shadowRadius: 10,
      elevation: 2,
    },
    row: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: Spacing.sm,
    },
    dot: {
      width: 10,
      height: 10,
      borderRadius: 5,
    },
    dotActive: {
      backgroundColor: t.fill.brand.strong,
    },
    dotDone: {
      backgroundColor: t.fill.neutral.strong,
    },
    dotNext: {
      backgroundColor: t.stroke.weak,
    },
    divider: {
      height: 1,
      width: '100%',
      backgroundColor: t.fill.neutral.weak,
    },
    labelActive: {
      fontSize: 12.5,
      fontWeight: FontWeight.bold,
      color: t.text.strong,
    },
    valueActive: {
      marginLeft: 'auto',
      fontSize: 12.5,
      fontWeight: FontWeight.bold,
      color: t.text.strong,
    },
    label: {
      fontSize: 12,
      color: t.text.weaker,
    },
    value: {
      marginLeft: 'auto',
      fontSize: 12,
      color: t.text.weaker,
    },
    nextBadge: {
      marginLeft: 'auto',
      backgroundColor: t.fill.brand.weak,
      borderRadius: Radius.full,
      paddingHorizontal: Spacing.sm,
      paddingVertical: 3,
    },
    nextBadgeText: {
      fontSize: 10,
      fontWeight: FontWeight.semibold,
      color: t.text.brand,
    },
  });
