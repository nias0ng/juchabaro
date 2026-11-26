import { StyleSheet } from 'react-native';

import { FontSize, FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    content: {
      padding: Spacing.md,
      gap: Spacing.lg,
    },
    section: {
      gap: Spacing.base,
    },
    sectionTitle: {
      fontSize: FontSize.base,
      fontWeight: FontWeight.bold,
      color: t.text.strong,
    },
    groupTitle: {
      fontSize: FontSize.sm,
      fontWeight: FontWeight.semibold,
      color: t.text.weak,
    },
    swatchGrid: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: Spacing.sm,
    },
    swatch: {
      width: 156,
      flexDirection: 'row',
      alignItems: 'center',
      gap: Spacing.sm,
      padding: Spacing.sm,
      borderRadius: Radius.md,
      backgroundColor: t.background.raised,
      borderWidth: 1,
      borderColor: t.stroke.weak,
    },
    chip: {
      width: 28,
      height: 28,
      borderRadius: Radius.sm,
      borderWidth: 1,
      borderColor: t.stroke.strong,
    },
    swatchText: {
      flex: 1,
    },
    swatchName: {
      fontSize: FontSize.xs,
      fontWeight: FontWeight.semibold,
      color: t.text.strong,
    },
    swatchValue: {
      fontSize: FontSize.xs,
      color: t.text.weaker,
    },
    row: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: Spacing.sm,
    },
  });
