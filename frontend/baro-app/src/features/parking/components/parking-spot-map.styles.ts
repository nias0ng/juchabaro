import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  mapPreview: {
    width: '100%',
    minHeight: Spacing.xxxl * 2,
    borderRadius: Radius.md + 6,
    backgroundColor: Palette.lilac25,
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
    backgroundColor: Palette.lilac100,
    alignItems: 'center',
    justifyContent: 'center',
  },
  mapCellMissing: {
    backgroundColor: Palette.lilac25,
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
    backgroundColor: Palette.lilac25,
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
    alignItems: 'center',
    justifyContent: 'center',
  },
  accessBlockText: {
    color: Palette.gray500,
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
  mapCellSelected: {
    borderWidth: 2,
    borderColor: Palette.violet500,
  },
  mapCellLabel: {
    fontSize: 9,
    fontWeight: FontWeight.bold,
    textAlign: 'center',
  },
  zoneTypeLabel: {
    color: Palette.gray600,
    fontSize: 8,
    lineHeight: 10,
    fontWeight: FontWeight.medium,
  },
  spotCodeLabel: {
    color: Palette.gray975,
  },
});
