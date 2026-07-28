import { StyleSheet } from 'react-native';

import {
  ContentWidth,
  ControlHeight,
  FontSize,
  FontWeight,
  LineHeight,
  Palette,
  Radius,
  Spacing,
} from '@/styles';

export const styles = StyleSheet.create({
  container: {
    flexGrow: 1,
    paddingBottom: Spacing.base,
  },
  topNav: {
    width: '100%',
    minHeight: ControlHeight.lg,
  },
  brand: {
    fontSize: FontSize.lg,
    fontWeight: FontWeight.bold,
    color: Palette.gray950,
  },
  main: {
    flexGrow: 1,
    width: '100%',
    justifyContent: 'center',
  },
  mainWide: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.xxl,
  },
  heroSection: {
    width: '100%',
    alignItems: 'center',
    paddingVertical: Spacing.lg,
  },
  heroSectionWide: {
    flex: 1,
  },
  heroGradient: {
    width: '100%',
    maxWidth: ContentWidth.compact,
    aspectRatio: 1,
    borderRadius: Radius.xxl,
    overflow: 'hidden',
    paddingVertical: Spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  heroCard: {
    width: '88%',
    height: '100%',
    borderRadius: Radius.xl,
    overflow: 'hidden',
    backgroundColor: Palette.white,
    shadowColor: Palette.gray950,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.04,
    shadowRadius: 20,
    elevation: 2,
  },
  heroImage: {
    width: '100%',
    height: '100%',
  },
  badge: {
    position: 'absolute',
    right: '5%',
    bottom: '10%',
    borderRadius: Radius.md,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.5)',
    shadowColor: Palette.black,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.1,
    shadowRadius: 15,
    elevation: 4,
  },
  badgeBlur: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.base,
    padding: Spacing.md,
    backgroundColor: 'rgba(255, 255, 255, 0.35)',
  },
  badgeIcon: {
    width: Spacing.xl,
    aspectRatio: 31 / 35,
  },
  badgeTitle: {
    fontSize: FontSize.sm,
    fontWeight: FontWeight.semibold,
    color: Palette.violet600,
    letterSpacing: 0.24,
  },
  badgeSubtitle: {
    marginTop: Spacing.xxs,
    fontSize: FontSize.xs,
    color: Palette.gray700,
  },
  details: {
    width: '100%',
    alignItems: 'center',
  },
  detailsWide: {
    flex: 1,
    maxWidth: ContentWidth.compact,
  },
  valueProp: {
    width: '100%',
    paddingVertical: Spacing.xl,
    paddingHorizontal: Spacing.sm,
  },
  heading: {
    fontSize: FontSize.xl,
    lineHeight: LineHeight.xl,
    fontWeight: FontWeight.bold,
    color: Palette.violet500,
    textAlign: 'center',
    letterSpacing: -0.4,
  },
  subheading: {
    fontSize: FontSize.md,
    lineHeight: LineHeight.md,
    color: Palette.gray500,
    textAlign: 'center',
  },
  buttonGroup: {
    width: '100%',
    paddingBottom: Spacing.lg,
  },
  wideButton: {
    flex: 1,
  },
  footer: {
    paddingVertical: Spacing.sm,
    fontSize: FontSize.xs,
    fontWeight: FontWeight.medium,
    color: Palette.gray700,
    opacity: 0.6,
    textAlign: 'center',
  },
});
