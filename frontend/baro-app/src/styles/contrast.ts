import type { ColorTokens } from './color-tokens';

/** WCAG 2.1 상대 휘도. 6자리 hex만 받는다. */
function relativeLuminance(hex: string): number {
  if (!/^#[0-9a-fA-F]{6}$/.test(hex)) {
    throw new Error(`대비 계산은 6자리 hex만 지원합니다: ${hex}`);
  }

  const [r, g, b] = [1, 3, 5]
    .map((start) => parseInt(hex.slice(start, start + 2), 16) / 255)
    .map((channel) => (channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4));

  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrastRatio(fg: string, bg: string): number {
  const a = relativeLuminance(fg);
  const b = relativeLuminance(bg);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

/** 본문 글자 4.5, 아이콘 3 (WCAG 2.1 AA). */
type MinRatio = 4.5 | 3;

export type ContrastPair = {
  name: string;
  fg: (t: ColorTokens) => string;
  bg: (t: ColorTokens) => string;
  min: MinRatio;
};

type Mode = 'light' | 'dark';

const BACKGROUNDS = ['neutral', 'weak', 'raised'] as const;
const NEUTRAL_TEXTS = ['strong', 'weak', 'weaker', 'brand', 'error', 'warning', 'success', 'info'] as const;
const BADGE_TONES = ['brand', 'error', 'warning', 'success', 'info'] as const;
const STRONG_FILLS = ['brand', 'error', 'inverse'] as const;

/**
 * 글자·아이콘 토큰이 실제로 놓이는 배경과의 조합.
 * 테두리(stroke)는 구분선 용도라 검사하지 않는다.
 */
export const CONTRAST_PAIRS: ContrastPair[] = [
  ...NEUTRAL_TEXTS.flatMap((text) =>
    BACKGROUNDS.map(
      (background): ContrastPair => ({
        name: `text.${text} on background.${background}`,
        fg: (t) => t.text[text],
        bg: (t) => t.background[background],
        min: 4.5,
      }),
    ),
  ),
  ...BADGE_TONES.map(
    (tone): ContrastPair => ({
      name: `text.${tone} on fill.${tone}.weak`,
      fg: (t) => t.text[tone],
      bg: (t) => t.fill[tone].weak,
      min: 4.5,
    }),
  ),
  {
    name: 'text.weak on fill.neutral.weak',
    fg: (t) => t.text.weak,
    bg: (t) => t.fill.neutral.weak,
    min: 4.5,
  },
  {
    name: 'text.weaker on fill.neutral.weak',
    fg: (t) => t.text.weaker,
    bg: (t) => t.fill.neutral.weak,
    min: 4.5,
  },
  ...STRONG_FILLS.map(
    (tone): ContrastPair => ({
      name: `text.inverse on fill.${tone}.strong`,
      fg: (t) => t.text.inverse,
      bg: (t) => t.fill[tone].strong,
      min: 4.5,
    }),
  ),
  ...BACKGROUNDS.map(
    (background): ContrastPair => ({
      name: `icon.weak on background.${background}`,
      fg: (t) => t.icon.weak,
      bg: (t) => t.background[background],
      min: 3,
    }),
  ),
];

/** 사용자가 지금 값을 유지하기로 한 미달 조합. 사유와 함께 적는다. */
export const KNOWN_EXCEPTIONS: { name: string; mode: Mode; reason: string }[] = [];

export type ContrastFailure = { name: string; ratio: number; min: number; excepted: boolean };

/** 기준에 못 미치는 조합만 돌려준다. */
export function checkContrast(tokens: ColorTokens, mode: Mode): ContrastFailure[] {
  return CONTRAST_PAIRS.flatMap((pair) => {
    const ratio = contrastRatio(pair.fg(tokens), pair.bg(tokens));
    if (ratio >= pair.min) return [];

    const excepted = KNOWN_EXCEPTIONS.some((item) => item.name === pair.name && item.mode === mode);
    return [{ name: pair.name, ratio, min: pair.min, excepted }];
  });
}
