import Svg, { Path } from 'react-native-svg';

type IconGlyphProps = {
  /** 여러 path로 나뉜 아이콘(예: 주차 현황 "P" 아이콘)은 배열로 넘긴다. */
  d: string | string[];
  size?: number;
  color: string;
  variant?: 'stroke' | 'fill';
  viewBoxSize?: number;
  strokeWidth?: number;
  /** fill 아이콘은 path 자체가 채워진 도형이라 strokeWidth로 굵기 조절이 안 된다.
   * 같은 색 외곽선을 얹어서 더 굵어 보이게 하고 싶을 때만 지정한다. */
  fillOutlineWidth?: number;
};

/** BottomNavBar 아이콘 공용 렌더러. stroke(홈/내정보)와 fill(요청/주차 현황) 두 path 스타일을 모두 지원한다. */
export function IconGlyph({
  d,
  size = 22,
  color,
  variant = 'stroke',
  viewBoxSize = 22,
  strokeWidth = 2,
  fillOutlineWidth = 0,
}: IconGlyphProps) {
  const paths = Array.isArray(d) ? d : [d];

  return (
    <Svg width={size} height={size} viewBox={`0 0 ${viewBoxSize} ${viewBoxSize}`} fill="none">
      {paths.map((path) =>
        variant === 'stroke' ? (
          <Path key={path} d={path} stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" />
        ) : (
          <Path
            key={path}
            d={path}
            fill={color}
            stroke={fillOutlineWidth > 0 ? color : undefined}
            strokeWidth={fillOutlineWidth > 0 ? fillOutlineWidth : undefined}
            strokeLinejoin={fillOutlineWidth > 0 ? 'round' : undefined}
          />
        ),
      )}
    </Svg>
  );
}
