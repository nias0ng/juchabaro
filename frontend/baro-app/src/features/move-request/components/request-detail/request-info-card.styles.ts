import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    container: {
      gap: Spacing.base,
    },
    violationRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      backgroundColor: t.background.raised,
      borderRadius: Radius.lg,
      paddingHorizontal: Spacing.md,
      paddingVertical: Spacing.base + 2,
    },
    violationBadgeText: {
      fontSize: 13,
      fontWeight: FontWeight.bold,
      color: t.text.error,
    },
    infoGrid: {
      flexDirection: 'row',
      gap: Spacing.base,
    },
    infoCard: {
      flex: 1,
      gap: Spacing.xs + 1,
      backgroundColor: t.background.raised,
      borderRadius: Radius.lg,
      paddingHorizontal: Spacing.md,
      paddingVertical: Spacing.base + 2,
    },
    label: {
      fontSize: 12,
      color: t.text.weaker,
    },
    value: {
      fontSize: 16,
      fontWeight: FontWeight.bold,
      color: t.text.strong,
    },
  });
