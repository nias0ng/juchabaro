import { StyleSheet } from 'react-native';

import { ControlHeight, FontWeight, Palette, Radius, Spacing } from '@/styles';

// 피그마 로그아웃 색상은 공통 red500보다 어두워 이 컴포넌트 안에서만 사용한다.
export const LOGOUT_COLOR = '#ba1a1a';

export const styles = StyleSheet.create({
  logoutButton: {
    alignItems: 'center',
    justifyContent: 'center',
    width: '100%',
    minHeight: ControlHeight.md,
    paddingVertical: Spacing.base + 1,
    borderRadius: Radius.full,
    backgroundColor: Palette.white,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.05,
    shadowRadius: 9,
    elevation: 1,
  },
  logoutButtonPressed: {
    backgroundColor: Palette.gray50,
  },
  logoutText: {
    fontSize: 14,
    fontWeight: FontWeight.medium,
    color: LOGOUT_COLOR,
  },
  withdrawLink: {
    alignItems: 'center',
    paddingTop: Spacing.xs,
    paddingBottom: Spacing.xl,
  },
  withdrawText: {
    fontSize: 12.5,
    fontWeight: FontWeight.medium,
    color: Palette.gray400,
    textDecorationLine: 'underline',
  },
});
