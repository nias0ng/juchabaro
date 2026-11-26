import { StyleSheet } from 'react-native';

import { FontWeight, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    overlay: {
      flex: 1,
      backgroundColor: t.overlay.scrim,
      alignItems: 'center',
      justifyContent: 'center',
      padding: Spacing.lg,
    },
    sheet: {
      width: '100%',
      maxWidth: 360,
      maxHeight: '85%',
      overflow: 'hidden',
      borderRadius: 26,
      backgroundColor: t.background.raised,
      padding: Spacing.lg,
      gap: Spacing.base,
      shadowColor: t.shadow,
      shadowOffset: { width: 0, height: 20 },
      shadowOpacity: 0.18,
      shadowRadius: 22,
      elevation: 6,
    },
    scrollArea: {
      flexShrink: 1,
    },
    scrollContent: {
      gap: Spacing.base,
      paddingBottom: Spacing.xs,
    },
    headerRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    title: {
      fontSize: 16,
      fontWeight: FontWeight.bold,
      color: t.text.strong,
    },
    closeIcon: {
      fontSize: 16,
      color: t.text.weaker,
    },
    subtitle: {
      fontSize: 12,
      color: t.text.weaker,
    },
  });
