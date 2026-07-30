import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.base,
    width: '100%',
    height: 92,
    borderRadius: 22,
    paddingHorizontal: Spacing.md + 2,
  },
  iconBadge: {
    width: 34,
    height: 34,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: Spacing.base,
    backgroundColor: 'rgba(255,255,255,0.22)',
  },
  textGroup: {
    gap: 2,
  },
  title: {
    fontSize: 14,
    fontWeight: FontWeight.bold,
    color: Palette.white,
  },
  subtitle: {
    fontSize: 11,
    color: Palette.white,
    opacity: 0.85,
  },
});
