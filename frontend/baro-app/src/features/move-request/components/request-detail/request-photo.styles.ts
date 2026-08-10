import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    width: '100%',
    aspectRatio: 16 / 9,
    backgroundColor: Palette.black,
    overflow: 'hidden',
  },
  carousel: {
    ...StyleSheet.absoluteFillObject,
  },
  photo: {
    height: '100%',
  },
  tapZones: {
    ...StyleSheet.absoluteFillObject,
    flexDirection: 'row',
    zIndex: 1,
  },
  edgeTapZone: {
    width: '15%',
  },
  centerTapZone: {
    flex: 1,
  },
  viewerBackdrop: {
    flex: 1,
    backgroundColor: Palette.black,
  },
  viewerCloseButton: {
    position: 'absolute',
    top: Spacing.xxl,
    right: Spacing.lg,
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(255, 255, 255, 0.16)',
  },
  viewerCloseText: {
    fontSize: 16,
    color: Palette.white,
  },
  viewerIndicator: {
    position: 'absolute',
    alignSelf: 'center',
    bottom: Spacing.xxl,
    paddingHorizontal: Spacing.sm + 2,
    paddingVertical: Spacing.xs,
    borderRadius: Radius.full,
    backgroundColor: 'rgba(255, 255, 255, 0.16)',
  },
  indicator: {
    position: 'absolute',
    right: Spacing.sm + 4,
    bottom: Spacing.sm + 4,
    zIndex: 2,
    paddingHorizontal: Spacing.sm + 2,
    paddingVertical: Spacing.xs,
    borderRadius: Radius.full,
    backgroundColor: 'rgba(27, 27, 35, 0.68)',
  },
  indicatorText: {
    fontSize: 11,
    fontWeight: FontWeight.semibold,
    color: Palette.white,
    textShadowColor: 'rgba(0, 0, 0, 0.6)',
    textShadowOffset: { width: 0, height: 1 },
    textShadowRadius: 3,
  },
});
