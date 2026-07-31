import { StyleSheet } from 'react-native';

import { Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
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
    backgroundColor: Palette.gray100,
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
    backgroundColor: 'rgba(20, 22, 28, 0.65)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  removeIcon: {
    fontSize: 11,
    color: Palette.white,
  },
  addSlot: {
    width: 76,
    height: 74,
    borderRadius: Radius.lg + 2,
    backgroundColor: Palette.white,
    borderWidth: 1,
    borderStyle: 'dashed',
    borderColor: Palette.gray300,
    alignItems: 'center',
    justifyContent: 'center',
  },
  addIcon: {
    fontSize: 20,
    color: Palette.gray400,
  },
});
