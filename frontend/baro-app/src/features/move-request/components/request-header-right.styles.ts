import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    badge: {
      borderRadius: Radius.full,
      paddingHorizontal: Spacing.sm + 4,
      paddingVertical: Spacing.xs + 1,
    },
    manualBadge: {
      backgroundColor: t.fill.info.weak,
    },
    aiBadge: {
      backgroundColor: t.fill.success.weak,
    },
    badgeText: {
      fontSize: 10.5,
      fontWeight: FontWeight.bold,
    },
    manualText: {
      color: t.text.info,
    },
    aiText: {
      color: t.text.success,
    },
  });
