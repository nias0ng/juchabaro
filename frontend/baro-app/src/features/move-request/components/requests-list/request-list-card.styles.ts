import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Shadows, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    card: {
      width: '100%',
      backgroundColor: t.background.raised,
      borderRadius: Radius.xl,
      padding: Spacing.md + 2,
      gap: Spacing.sm + 2,
      ...Shadows.card,
      elevation: 3,
    },
    cardResponded: {
      borderWidth: 1,
      borderColor: t.stroke.brand,
    },
    topRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    timestamp: {
      fontSize: 11.5,
      color: t.text.weaker,
    },
    plateBlock: {
      gap: Spacing.xxs,
    },
    plate: {
      fontSize: 19,
      fontWeight: FontWeight.bold,
      color: t.text.strong,
      letterSpacing: 0.3,
    },
    situation: {
      fontSize: 12.5,
      color: t.text.weaker,
    },
    countdownBox: {
      width: '100%',
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      backgroundColor: t.fill.neutral.weak,
      borderRadius: Radius.lg,
      paddingHorizontal: Spacing.base + 2,
      paddingVertical: Spacing.base,
    },
    countdownMessage: {
      fontSize: 12.5,
      color: t.text.weak,
    },
    countdownValue: {
      fontSize: 14,
      fontWeight: FontWeight.bold,
      color: t.text.brand,
    },
    closedSummary: {
      fontSize: 13,
      fontWeight: FontWeight.bold,
      color: t.text.info,
    },
  });
