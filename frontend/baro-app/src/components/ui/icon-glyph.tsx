import Svg, { Path } from 'react-native-svg';

type IconGlyphProps = {
  d: string;
  size?: number;
  color: string;
  variant?: 'stroke' | 'fill';
  viewBoxSize?: number;
  strokeWidth?: number;
};

/** BottomNavBar 아이콘 공용 렌더러. stroke(홈/알림/내정보)와 fill(요청) 두 path 스타일을 모두 지원한다. */
export function IconGlyph({
  d,
  size = 22,
  color,
  variant = 'stroke',
  viewBoxSize = 22,
  strokeWidth = 2,
}: IconGlyphProps) {
  return (
    <Svg width={size} height={size} viewBox={`0 0 ${viewBoxSize} ${viewBoxSize}`} fill="none">
      {variant === 'stroke' ? (
        <Path d={d} stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" />
      ) : (
        <Path d={d} fill={color} />
      )}
    </Svg>
  );
}
