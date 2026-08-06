import { StyleSheet } from 'react-native';

import { MaxContentWidth, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  header: {
    paddingHorizontal: Spacing.lg,
    paddingTop: Spacing.lg,
  },
  // RequestDetailBody의 하위 상태 섹션(대기/초과/이관/완료 등)이 이미 각자 좌우 패딩을 갖고 있어서,
  // ResponsiveContainer의 강제 패딩을 쓰면 넓은 화면이 아니어도 이중 패딩이 생긴다.
  // 그래서 패딩 없이 최대 폭 제한만 건다.
  content: {
    flexGrow: 1,
    width: '100%',
    maxWidth: MaxContentWidth,
    alignSelf: 'center',
  },
});
