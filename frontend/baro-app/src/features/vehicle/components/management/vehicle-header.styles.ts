import { StyleSheet } from 'react-native';

import { FontWeight, Palette } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    height: 44,
    // 좌우 여백은 ResponsiveContainer의 gutter가 이미 담당한다 — 여기서 또 주면 이중으로 들여써진다.
    paddingTop: 4,
    paddingBottom: 10,
  },
  backButton: {
    width: 38,
    height: 38,
    borderRadius: 19,
    backgroundColor: Palette.white,
    alignItems: 'center',
    justifyContent: 'center',
  },
  backIcon: {
    fontSize: 16,
    color: Palette.gray975,
  },
  title: {
    paddingLeft: 12,
    fontSize: 15,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
});
