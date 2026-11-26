import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    badge: {
      borderRadius: Radius.full,
      paddingHorizontal: Spacing.sm + 3,
      paddingVertical: Spacing.xxs + 3,
    },
    text: {
      fontSize: 11,
      fontWeight: FontWeight.bold,
    },
    badgeResponded: {
      backgroundColor: t.fill.brand.weak,
    },
    textResponded: {
      color: t.text.brand,
    },
    badgePending: {
      backgroundColor: t.fill.warning.weak,
    },
    textPending: {
      color: t.text.warning,
    },
    badgeReminder: {
      backgroundColor: t.fill.warning.weak,
    },
    textReminder: {
      color: t.text.warning,
    },
    badgeEscalated: {
      backgroundColor: t.fill.warning.weak,
    },
    textEscalated: {
      color: t.text.warning,
    },
    badgeClosed: {
      backgroundColor: t.fill.info.weak,
    },
    textClosed: {
      color: t.text.info,
    },
  });
