import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.md,
  },
  /** 그림자와 원 안쪽 이미지 자르기(overflow:hidden)를 같은 View에 두면 iOS에서 그림자가 잘려서 두 겹으로 나눈다. */
  iconShadow: {
    width: 80,
    height: 80,
    borderRadius: 40,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 14 },
    shadowOpacity: 0.09,
    shadowRadius: 17,
    elevation: 4,
  },
  iconCircle: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: Palette.white,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  /** 원 안에 꽉 차 보이도록 실제 원보다 크게 그린 뒤 iconCircle의 overflow:hidden으로 잘라낸다. */
  carIcon: {
    width: 128,
    height: 128,
  },
  title: {
    fontSize: 15,
    fontWeight: FontWeight.semibold,
    color: Palette.gray975,
  },
  description: {
    fontSize: 12,
    color: Palette.gray500,
  },
});
