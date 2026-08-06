import { StyleSheet } from 'react-native';

import { MaxContentWidth, Palette } from '@/styles';

export const styles = StyleSheet.create({
  // 배경/구분선은 화면 전체 폭을 채우고, 실제 탭 아이콘 줄만 아래 tabsRow에서 폭을 제한한다 —
  // 안 그러면 넓은 화면에서 탭 줄 양옆에 배경색이 안 칠해진 빈 여백이 생긴다.
  container: {
    width: '100%',
    borderTopWidth: 1,
    paddingTop: 10,
    paddingBottom: 14,
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
    gap: 4,
  },
  iconContainer: {
    width: 24,
    height: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  // Figma상 "주차 현황" 아이콘만 다른 탭보다 크게 그려진다.
  iconContainerLarge: {
    width: 29,
    height: 29,
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
