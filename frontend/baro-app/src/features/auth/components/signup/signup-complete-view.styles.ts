import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    width: '100%',
    alignItems: 'center',
    paddingTop: Spacing.xl,
  },
  iconCircle: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: Palette.white,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 14 },
    shadowOpacity: 0.09,
    shadowRadius: 17,
    elevation: 4,
  },
  iconGradient: {
    width: 34,
    height: 34,
    borderRadius: 12,
  },
  heading: {
    fontSize: 22,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    letterSpacing: -0.3,
    textAlign: 'center',
    paddingTop: Spacing.lg,
  },
  subheading: {
    fontSize: 13,
    color: Palette.gray500,
    textAlign: 'center',
    lineHeight: 22.75,
    paddingTop: Spacing.sm,
  },
  profileCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.base,
    width: '100%',
    borderRadius: 26,
    backgroundColor: Palette.white,
    padding: Spacing.md,
    marginTop: Spacing.lg,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.07,
    shadowRadius: 15,
    elevation: 3,
  },
  profileInfo: {
    flex: 1,
    gap: 2,
  },
  profileName: {
    fontSize: 13,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  profileAddress: {
    fontSize: 11.5,
    color: Palette.gray500,
  },
  residentBadge: {
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm,
    paddingVertical: 5,
    backgroundColor: '#fff0eb',
  },
  residentBadgeText: {
    fontSize: 10.5,
    fontWeight: FontWeight.bold,
    color: Palette.orange600,
  },
  actions: {
    width: '100%',
    gap: Spacing.sm,
    paddingTop: Spacing.xxl,
  },
});
