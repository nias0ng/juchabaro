import { StyleSheet } from 'react-native';

import { Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    row: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: Spacing.sm + 2,
    },
    slot: {
      width: 88,
      height: 74,
      borderRadius: Radius.lg + 2,
      overflow: 'hidden',
      backgroundColor: t.fill.neutral.weak,
    },
    slotImage: {
      width: '100%',
      height: '100%',
    },
    removeButton: {
      position: 'absolute',
      top: Spacing.xxs,
      right: Spacing.xxs,
      width: 20,
      height: 20,
      borderRadius: 10,
      backgroundColor: t.overlay.scrimStrong,
      alignItems: 'center',
      justifyContent: 'center',
    },
    removeIcon: {
      fontSize: 11,
      color: t.overlay.onMediaText,
    },
    addSlot: {
      width: 76,
      height: 74,
      borderRadius: Radius.lg + 2,
      backgroundColor: t.background.raised,
      borderWidth: 1,
      borderStyle: 'dashed',
      borderColor: t.stroke.strong,
      alignItems: 'center',
      justifyContent: 'center',
    },
    addIcon: {
      fontSize: 20,
      color: t.text.weaker,
    },
  });
