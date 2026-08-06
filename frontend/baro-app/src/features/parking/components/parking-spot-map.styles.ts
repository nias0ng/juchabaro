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
    width: 32,
    height: 41,
    borderRadius: 7,
    backgroundColor: Palette.gray100,
    alignItems: 'center',
    justifyContent: 'center',
  },
  mapCellMissing: {
    backgroundColor: Palette.violet50,
  },
  floorLayout: {
    alignSelf: 'center',
    gap: Spacing.sm,
  },
  layoutRowGroup: {
    gap: Spacing.sm,
  },
  layoutDivider: {
    height: 22,
    backgroundColor: Palette.violet50,
  },
  layoutRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  sideCell: {
    width: 40,
    height: 32,
  },
  gapSlot: {
    width: 48,
    alignItems: 'center',
    justifyContent: 'center',
  },
  accessBlock: {
    width: 40,
    height: 32,
    borderRadius: Radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
  },
  exitBlock: {
    backgroundColor: Palette.blue500,
  },
  entryBlock: {
    backgroundColor: Palette.emerald500,
  },
  accessBlockText: {
    color: Palette.white,
    fontSize: 10,
    fontWeight: FontWeight.bold,
  },
  mainCells: {
    flexDirection: 'row',
    gap: 5,
  },
  mainCell: {
    width: 32,
    height: 41,
  },
  mapCellOther: {
    backgroundColor: Palette.violet300,
  },
  mapCellMine: {
    backgroundColor: Palette.yellow100,
  },
  mapCellEmptyDisabled: {
    backgroundColor: Palette.green100,
  },
  mapCellEmptyEv: {
    backgroundColor: Palette.sky100,
  },
  mapCellSelected: {
    borderWidth: 2,
    borderColor: Palette.violet500,
  },
  mapCellLabel: {
    fontSize: 9,
    fontWeight: FontWeight.bold,
  },
  mineLabel: {
    color: Palette.yellow700,
    fontWeight: FontWeight.regular,
  },  
  otherLabel: {
    color: Palette.purple700,
    fontWeight: FontWeight.regular,
  },
  disabledLabel: {
    color: Palette.emerald500,
    fontWeight: FontWeight.regular,
  },
  evLabel: {
    color: Palette.blue600,
    fontWeight: FontWeight.regular,
  },
  spotCodeLabel: {
    color: Palette.gray975,
  },
});
