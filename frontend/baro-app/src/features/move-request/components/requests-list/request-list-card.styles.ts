import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  card: {
    width: '100%',
    backgroundColor: Palette.white,
    borderRadius: Radius.xl,
    padding: Spacing.md + 2,
    gap: Spacing.sm + 2,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.06,
    shadowRadius: 13,
    elevation: 3,
  },
  // 응답 완료 카드만 테두리를 추가로 보여준다.
  cardResponded: {
    borderWidth: 1,
    borderColor: Palette.lavender100,
  },
  topRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  timestamp: {
    fontSize: 11.5,
    color: Palette.gray400,
  },
  plateBlock: {
    gap: Spacing.xxs,
  },
  plate: {
    fontSize: 19,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    letterSpacing: 0.3,
  },
  situation: {
    fontSize: 12.5,
    color: Palette.gray500,
  },
  countdownBox: {
    width: '100%',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#f5f4fb',
    borderRadius: Radius.lg,
    paddingHorizontal: Spacing.base + 2,
    paddingVertical: Spacing.base,
  },
  countdownMessage: {
    fontSize: 12.5,
    color: '#5c6070',
  },
  countdownValue: {
    fontSize: 14,
    fontWeight: FontWeight.bold,
    color: Palette.violet500,
  },
  closedSummary: {
    fontSize: 13,
    fontWeight: FontWeight.bold,
    color: Palette.blue600,
  },
});
