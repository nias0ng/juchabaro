import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    width: '100%',
    gap: Spacing.xl,
  },
  profileCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.base,
    width: '100%',
    borderRadius: 26,
    backgroundColor: Palette.white,
    padding: Spacing.md,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.07,
    shadowRadius: 15,
    elevation: 3,
  },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Palette.violet500,
  },
  avatarText: {
    fontSize: 18,
    fontWeight: FontWeight.bold,
    color: Palette.white,
  },
  profileInfo: {
    flex: 1,
    gap: 2,
  },
  profileName: {
    fontSize: 15,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  profileRole: {
    fontSize: 12,
    color: Palette.gray500,
  },
  menuList: {
    width: '100%',
    borderRadius: Radius.lg,
    backgroundColor: Palette.white,
    overflow: 'hidden',
  },
  menuRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.base,
    borderBottomWidth: 1,
    borderBottomColor: Palette.gray100,
  },
  menuRowPressed: {
    backgroundColor: Palette.gray50,
  },
  menuRowDisabled: {
    opacity: 0.5,
  },
  menuLabel: {
    fontSize: 14,
    fontWeight: FontWeight.medium,
    color: Palette.gray975,
  },
  menuLabelDisabled: {
    color: Palette.gray500,
  },
  menuBadge: {
    fontSize: 10.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray500,
    backgroundColor: Palette.gray100,
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm,
    paddingVertical: 3,
  },
});
