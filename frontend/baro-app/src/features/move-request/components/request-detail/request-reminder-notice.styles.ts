import { StyleSheet } from 'react-native';

import { Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    borderWidth: 1,
    borderStyle: 'dashed',
    borderColor: Palette.orange400,
    backgroundColor: Palette.orange50,
    borderRadius: Radius.lg,
    paddingHorizontal: Spacing.md - 1,
    paddingVertical: Spacing.sm + 3,
  },
  text: {
    fontSize: 13,
    lineHeight: 17.5,
    textAlign: 'center',
    color: '#a35b3d',
  },
});
