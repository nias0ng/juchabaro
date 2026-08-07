import { StyleSheet } from 'react-native';

import { MaxContentWidth, Palette } from '@/styles';

export const styles = StyleSheet.create({
  // 배경/구분선은 화면 전체 폭을 채우고, 실제 탭 아이콘 줄만 아래 tabsRow에서 폭을 제한한다 —
  // 안 그러면 넓은 화면에서 탭 줄 양옆에 배경색이 안 칠해진 빈 여백이 생긴다.
  container: {
    width: '100%',
    borderTopWidth: 1,
    paddingTop: 12,
    paddingBottom: 8,
  },
  tabsRow: {
    flexDirection: 'row',
    width: '100%',
    maxWidth: MaxContentWidth,
    alignSelf: 'center',
  },
  tab: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 1,
  },
  homeTab: {
    gap: 0,
  },
  iconContainer: {
    // 아이콘 원본 크기가 달라도 모든 탭의 라벨 기준선이 같도록 공통 슬롯을 사용한다.
    width: 24,
    height: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badge: {
    position: 'absolute',
    top: -2,
    right: -2,
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: Palette.red500,
  },
  label: {
    fontSize: 11,
    textAlign: 'center',
  },
});
