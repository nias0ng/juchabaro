import { StyleSheet } from 'react-native';

import { Palette, Radius } from '@/styles';

export const styles = StyleSheet.create({
  noticeBanner: {
    width: '100%',
    borderRadius: Radius.lg,
    backgroundColor: Palette.orange50,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  noticeText: {
    fontSize: 11,
    lineHeight: 18.7,
    color: Palette.orange600,
    textAlign: 'center',
  },
});
