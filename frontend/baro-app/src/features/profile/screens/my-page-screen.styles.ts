import { StyleSheet } from 'react-native';

import { ControlHeight, FontWeight, Palette, Spacing } from '@/styles';

// 피그마 로그아웃 텍스트/아이콘 색상(#ba1a1a). 기존 팔레트 red500과는 다른 톤이라 리터럴로 둔다.
export const LOGOUT_COLOR = '#ba1a1a';

export const styles = StyleSheet.create({
  logoutButton: {
    alignItems: 'center',
    justifyContent: 'center',
    width: '100%',
    minHeight: ControlHeight.md,
    paddingVertical: Spacing.base + 1,
    borderRadius: 999,
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
