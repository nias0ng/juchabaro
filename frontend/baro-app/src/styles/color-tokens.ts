import { Palette } from './colors';

/**
 * 용도 기반 색상 토큰.
 *
 * 이름 규칙: 요소.톤.강조
 * - 요소: text / icon / stroke / fill(요소 자체의 면) / background(화면·카드 바탕)
 * - 톤: 중립은 생략, brand / error / warning / success / info / inverse
 * - 강조: strong / weak / weaker
 *
 * 값은 모두 Palette 단계를 가리킨다. 색상 값을 직접 적는 곳은 overlay뿐이다.
 * 라이트와 다크는 같은 역할이 같은 대비 수준을 갖도록 맞췄고,
 * `npm run check:contrast`가 이를 검사한다.
 */
type Gradient = readonly [string, string, ...string[]];

export type ColorTokens = {
  text: {
    strong: string;
    weak: string;
    weaker: string;
    /** 진한 면(fill.*.strong) 위에 놓이는 글자. */
    inverse: string;
    brand: string;
    error: string;
    warning: string;
    success: string;
    info: string;
  };
  icon: {
    weak: string;
  };
  stroke: {
    weak: string;
    strong: string;
    brand: string;
    error: string;
    success: string;
  };
  fill: {
    brand: { strong: string; weak: string };
    error: { strong: string; weak: string };
    warning: { strong: string; weak: string };
    success: { strong: string; weak: string };
    info: { weak: string };
    neutral: { strong: string; weak: string };
    /** 바탕과 반대되는 면. 라이트에서는 진한 버튼, 다크에서는 밝은 버튼. */
    inverse: { strong: string };
  };
  background: {
    neutral: string;
    weak: string;
    /** 카드처럼 떠 있는 면. 다크에서는 그림자 대신 한 단계 밝은 면으로 높이를 표현한다. */
    raised: string;
  };
  gradient: {
    brand: Gradient;
    error: Gradient;
    warning: Gradient;
    /** 장식용. 모드와 무관하게 같은 값이다. */
    accent: Gradient;
  };
  /** 반투명 막과 사진 위 요소. 사진 위 값은 모드와 무관하다. */
  overlay: {
    scrim: string;
    scrimStrong: string;
    glass: string;
    onMediaFill: string;
    onMediaCaption: string;
    onMediaText: string;
    onMediaShadow: string;
    mediaBackdrop: string;
  };
  shadow: string;
};

const onMedia = {
  onMediaFill: 'rgba(255, 255, 255, 0.16)',
  onMediaCaption: 'rgba(27, 27, 35, 0.68)',
  onMediaText: Palette.white,
  onMediaShadow: 'rgba(0, 0, 0, 0.6)',
  mediaBackdrop: Palette.black,
} as const;

const accentGradient = [Palette.mint300, Palette.violet400] as const;

const light = {
  text: {
    strong: Palette.gray975,
    weak: Palette.gray600,
    weaker: Palette.gray550,
    inverse: Palette.white,
    brand: Palette.violet600,
    error: Palette.orange700,
    warning: Palette.orange800,
    success: Palette.teal700,
    info: Palette.blue700,
  },
  icon: {
    weak: Palette.gray450,
  },
  stroke: {
    weak: Palette.gray200,
    strong: Palette.gray300,
    brand: Palette.lavender100,
    error: Palette.orange400,
    success: Palette.emerald500,
  },
  fill: {
    brand: { strong: Palette.violet600, weak: Palette.violet75 },
    error: { strong: Palette.red600, weak: Palette.orange50 },
    warning: { strong: Palette.orange400, weak: Palette.orange50 },
    success: { strong: Palette.emerald500, weak: Palette.teal100 },
    info: { weak: Palette.sky100 },
    neutral: { strong: Palette.gray300, weak: Palette.gray100 },
    inverse: { strong: Palette.gray975 },
  },
  background: {
    neutral: Palette.white,
    weak: Palette.lilac25,
    raised: Palette.white,
  },
  gradient: {
    brand: [Palette.lavender50, Palette.lilac25, Palette.lilac25],
    error: [Palette.peach50, Palette.lilac25, Palette.lilac25],
    warning: [Palette.rose50, Palette.lilac25, Palette.lilac25],
    accent: accentGradient,
  },
  overlay: {
    scrim: 'rgba(20, 22, 28, 0.5)',
    scrimStrong: 'rgba(20, 22, 28, 0.65)',
    glass: 'rgba(255, 255, 255, 0.85)',
    ...onMedia,
  },
  shadow: Palette.gray975,
} as const satisfies ColorTokens;

const dark = {
  text: {
    strong: Palette.white,
    weak: Palette.gray400,
    weaker: Palette.gray425,
    inverse: Palette.gray950,
    brand: Palette.violet300,
    error: Palette.orange400,
    warning: Palette.peach300,
    success: Palette.mint300,
    info: Palette.blue300,
  },
  icon: {
    weak: Palette.gray500,
  },
  stroke: {
    weak: Palette.gray800,
    strong: Palette.gray750,
    brand: Palette.violet900,
    error: Palette.orange900,
    success: Palette.emerald500,
  },
  fill: {
    brand: { strong: Palette.violet300, weak: Palette.violet900 },
    error: { strong: Palette.red400, weak: Palette.orange950 },
    warning: { strong: Palette.orange400, weak: Palette.brown950 },
    success: { strong: Palette.emerald500, weak: Palette.teal950 },
    info: { weak: Palette.blue950 },
    neutral: { strong: Palette.gray750, weak: Palette.gray800 },
    inverse: { strong: Palette.gray100 },
  },
  background: {
    neutral: Palette.black,
    weak: Palette.gray975,
    raised: Palette.gray900,
  },
  gradient: {
    brand: [Palette.violet950, Palette.gray975, Palette.gray975],
    error: [Palette.orange950, Palette.gray975, Palette.gray975],
    warning: [Palette.brown950, Palette.gray975, Palette.gray975],
    accent: accentGradient,
  },
  overlay: {
    scrim: 'rgba(0, 0, 0, 0.6)',
    scrimStrong: 'rgba(0, 0, 0, 0.7)',
    glass: 'rgba(33, 34, 37, 0.85)',
    ...onMedia,
  },
  shadow: Palette.black,
} as const satisfies ColorTokens;

export const Tokens: { light: ColorTokens; dark: ColorTokens } = { light, dark };
