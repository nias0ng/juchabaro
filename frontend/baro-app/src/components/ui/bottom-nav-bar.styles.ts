import { StyleSheet } from 'react-native';

import { Palette } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    width: '100%',
    borderTopWidth: 1,
    paddingTop: 10,
    paddingBottom: 14,
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
