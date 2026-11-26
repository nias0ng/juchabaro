import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Shadows, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    container: {
      width: '100%',
      gap: Spacing.xs + 2,
      backgroundColor: t.background.raised,
      borderRadius: Radius.xl,
      padding: Spacing.md + 2,
      ...Shadows.card,
    },
    headerRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    plateNumber: {
      fontSize: 14.5,
      fontWeight: FontWeight.bold,
      color: t.text.strong,
    },
    statusBadge: {
      borderRadius: Radius.full,
      paddingHorizontal: Spacing.sm + 2,
      paddingVertical: Spacing.xs,
    },
    statusText: {
      fontSize: 11,
      fontWeight: FontWeight.bold,
    },
    eventType: {
      fontSize: 12.5,
      color: t.text.weaker,
    },
    message: {
      fontSize: 12.5,
      lineHeight: 19,
      color: t.text.weaker,
    },
    requestedAt: {
      fontSize: 11,
      color: t.text.weaker,
    },
  });
