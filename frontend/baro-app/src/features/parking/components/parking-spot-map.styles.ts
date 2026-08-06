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
    backgroundColor: Palette.lilac100,
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
  // 입구/출구는 실제 주차 상태 정보가 아니라 구조 안내라, 배경 박스 없이 글자만 둔다.
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
  // 차가 있는(사용 중) 칸은 보라색으로 표시한다.
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
  // 장애인/EV 구역 종류 안내. 칸이 작아서 꽉 차 보이지 않게 조금 더 작게 둔다.
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
