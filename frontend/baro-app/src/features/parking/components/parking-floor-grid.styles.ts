import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    width: '100%',
    backgroundColor: Palette.lilac50,
    borderRadius: 20,
    padding: Spacing.base,
    gap: Spacing.sm,
    overflow: 'hidden',
  },
  rowGroup: {
    gap: Spacing.sm,
  },
  divider: {
    height: 22,
    marginHorizontal: -Spacing.base,
    backgroundColor: Palette.lilac50,
  },
  rowWithSide: {
    flexDirection: 'row',
    alignItems: 'center',
    // sideCell은 그대로 두고 spots(4열 그리드)만 칸 하나(34) 크기만큼 더 오른쪽으로 민다.
    gap: Spacing.lg + 34,
  },
  row: {
    flex: 1,
    flexDirection: 'row',
    justifyContent: 'flex-start',
    gap: Spacing.xs + 1,
  },
  cell: {
    flex: 1,
    maxWidth: 34,
    aspectRatio: 0.78,
    borderRadius: 7,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Palette.lilac100,
  },
  // 오른쪽의 가로형 칸: 세로형 cell(34×44)과 같은 크기를 가로세로만 바꿔서 그린다(44×34).
  sideCell: {
    width: 44,
    height: 34,
    borderRadius: 7,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Palette.lilac100,
  },
  cellOccupied: {
    backgroundColor: Palette.lilac200,
  },
  cellViolation: {
    backgroundColor: Palette.peach100,
  },
  cellMine: {
    backgroundColor: Palette.mint100,
  },
  cellDisabled: {
    backgroundColor: Palette.sky100,
  },
  cellEv: {
    backgroundColor: Palette.teal100,
  },
  // 삭제된 자리: 칸 크기(자리)는 그대로 두고 배경색만 컨테이너와 같게 만들어 눈에 안 보이게 한다.
  cellDeleted: {
    backgroundColor: Palette.lilac50,
  },
  cellLabel: {
    fontSize: 9.5,
    fontWeight: FontWeight.bold,
    textAlign: 'center',
  },
  violationLabel: {
    color: Palette.orange600,
  },
  mineLabel: {
    color: Palette.teal600,
  },
  disabledLabel: {
    color: Palette.blue600,
    fontSize: 9,
  },
  evLabel: {
    color: Palette.teal600,
  },
});
