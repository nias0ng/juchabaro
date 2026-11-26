import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    container: {
      width: '100%',
      aspectRatio: 16 / 9,
      backgroundColor: t.overlay.mediaBackdrop,
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
      backgroundColor: t.overlay.mediaBackdrop,
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
      backgroundColor: t.overlay.onMediaFill,
    },
    viewerCloseText: {
      fontSize: 16,
      color: t.overlay.onMediaText,
    },
    viewerIndicator: {
      position: 'absolute',
      alignSelf: 'center',
      bottom: Spacing.xxl,
      paddingHorizontal: Spacing.sm + 2,
      paddingVertical: Spacing.xs,
      borderRadius: Radius.full,
      backgroundColor: t.overlay.onMediaFill,
    },
    indicator: {
      position: 'absolute',
      right: Spacing.sm + 4,
      bottom: Spacing.sm + 4,
      zIndex: 2,
      paddingHorizontal: Spacing.sm + 2,
      paddingVertical: Spacing.xs,
      borderRadius: Radius.full,
      backgroundColor: t.overlay.onMediaCaption,
    },
    indicatorText: {
      fontSize: 11,
      fontWeight: FontWeight.semibold,
      color: t.overlay.onMediaText,
      textShadowColor: t.overlay.onMediaShadow,
      textShadowOffset: { width: 0, height: 1 },
      textShadowRadius: 3,
    },
  });
