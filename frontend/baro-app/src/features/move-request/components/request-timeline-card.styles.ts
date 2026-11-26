import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    card: {
      width: '100%',
      backgroundColor: t.background.raised,
      borderRadius: Radius.xl,
      padding: Spacing.md + 2,
      gap: Spacing.base + 2,
      shadowColor: t.shadow,
      shadowOffset: { width: 0, height: 8 },
      shadowOpacity: 0.05,
      shadowRadius: 10,
      elevation: 2,
    },
    headerRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    headerLabel: {
      fontSize: 12.5,
      color: t.text.weaker,
    },
    headerValue: {
      fontSize: 15,
      fontWeight: FontWeight.semibold,
      color: t.text.strong,
    },
    title: {
      fontSize: 12.5,
      fontWeight: FontWeight.bold,
      color: t.text.strong,
    },
    row: {
      flexDirection: 'row',
      gap: Spacing.sm + 2,
    },
    dotColumn: {
      width: 9,
      alignItems: 'center',
    },
    dot: {
      width: 9,
      height: 9,
      borderRadius: 4.5,
      backgroundColor: t.fill.success.strong,
    },
    dotBrand: {
      backgroundColor: t.fill.brand.strong,
    },
    dotWarning: {
      backgroundColor: t.fill.warning.strong,
    },
    dotError: {
      backgroundColor: t.fill.error.strong,
    },
    line: {
      flex: 1,
      width: 2,
      marginTop: Spacing.xxs,
      backgroundColor: t.stroke.weak,
    },
    textColumn: {
      flex: 1,
      gap: Spacing.xxs,
    },
    textColumnSpaced: {
      paddingBottom: Spacing.base,
    },
    stepLabel: {
      fontSize: 12.5,
      fontWeight: FontWeight.bold,
      color: t.text.strong,
    },
    stepLabelBrand: {
      color: t.text.brand,
    },
    stepLabelWarning: {
      color: t.text.warning,
    },
    stepLabelError: {
      color: t.text.error,
    },
    stepDetail: {
      fontSize: 11,
      color: t.text.weaker,
    },
    pendingRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: Spacing.sm,
    },
    pendingDot: {
      width: 9,
      height: 9,
      borderRadius: 4.5,
      backgroundColor: t.stroke.weak,
    },
    pendingLabel: {
      flex: 1,
      fontSize: 12,
      color: t.text.weaker,
    },
    pendingStatus: {
      fontSize: 10.5,
      color: t.text.weaker,
    },
  });
