import { StyleSheet } from 'react-native';

import { Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  field: {
    width: '100%',
    minHeight: 90,
    backgroundColor: Palette.white,
    borderRadius: Radius.input,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.base + 2,
    fontSize: 13,
    lineHeight: 22.1,
    color: '#3d4250',
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.05,
    shadowRadius: 9,
    elevation: 2,
  },
});
