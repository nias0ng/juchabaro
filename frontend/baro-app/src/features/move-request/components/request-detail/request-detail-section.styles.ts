import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    root: {
      flex: 1,
    },
    mainCard: {
      flexGrow: 1,
      gap: Spacing.base + 1,
      backgroundColor: t.background.weak,
      paddingTop: Spacing.lg + 4,
      paddingBottom: Spacing.lg,
      paddingHorizontal: Spacing.md + 4,
      shadowColor: t.shadow,
      shadowOffset: { width: 0, height: -4 },
      shadowOpacity: 0.07,
      shadowRadius: 10,
      elevation: 4,
    },
    summary: {
      gap: Spacing.xs,
    },
    summaryMeta: {
      fontSize: 11.5,
      color: t.text.weaker,
    },
    summaryTitle: {
      fontSize: 19,
      lineHeight: 24.7,
      fontWeight: FontWeight.bold,
      color: t.text.strong,
    },
    summaryReason: {
      fontSize: 12.5,
      lineHeight: 21.25,
      color: t.text.weaker,
    },
    autoEscalation: {
      gap: Spacing.base + 1,
    },
    timerRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      backgroundColor: t.background.raised,
      borderRadius: Radius.lg,
      paddingHorizontal: Spacing.md,
      paddingVertical: Spacing.base + 2,
    },
    label: {
      fontSize: 12,
      color: t.text.weaker,
    },
    timerValue: {
      fontSize: 16,
      fontWeight: FontWeight.bold,
      color: t.text.error,
    },
  });
