import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    paddingTop: Spacing.lg,
    paddingBottom: Spacing.md,
  },
  title: {
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  // 뒤로가기 버튼이 있는 화면은 버튼 옆에 붙는 만큼 살짝 작고 위로 붙는 크기를 쓴다.
  titleWithBack: {
    fontSize: 19,
    marginTop: -2,
  },
  // 탭 루트 화면(요청/알림/내 정보)처럼 뒤로가기가 없는 화면은 기존 크기를 그대로 유지한다.
  titleWithoutBack: {
    fontSize: 21,
  },
  right: {
    marginLeft: 'auto',
  },
});
