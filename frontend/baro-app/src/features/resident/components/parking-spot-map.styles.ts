import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  mapPreview: {
    width: '100%',
    minHeight: Spacing.xxxl * 2,
    borderRadius: Radius.md + 6,
    backgroundColor: Palette.violet50,
    paddingVertical: Spacing.base,
    paddingHorizontal: Spacing.lg,
    gap: Spacing.md,
  },
  messageContainer: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  message: {
    fontSize: 12,
    color: Palette.gray500,
    textAlign: 'center',
  },
  mapRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: Spacing.xs,
  },
  mapCell: {
    flex: 1,
    maxWidth: 32,
    aspectRatio: 0.78,
    borderRadius: 7,
    backgroundColor: Palette.gray100,
    alignItems: 'center',
    justifyContent: 'center',
  },
  mapCellOccupied: {
    backgroundColor: Palette.violet300,
  },
  mapCellViolation: {
    backgroundColor: Palette.peach100,
  },
  mapCellMine: {
    backgroundColor: Palette.mint100,
  },
  mapCellDisabled: {
    backgroundColor: Palette.sky100,
  },
  mapCellEv: {
    backgroundColor: Palette.teal100,
  },
  mapCellLabel: {
    fontSize: 9,
    fontWeight: FontWeight.bold,
  },
  violationLabel: {
    color: Palette.orange600,
  },
  mineLabel: {
    color: Palette.emerald500,
  },
  disabledLabel: {
    color: Palette.blue600,
  },
  evLabel: {
    color: Palette.teal600,
    fontWeight: FontWeight.regular,
  },
});
