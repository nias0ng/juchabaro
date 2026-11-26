// 색상 토큰의 글자·아이콘 대비를 WCAG AA 기준으로 검사한다.
// 사용법: npm run check:contrast
import { Tokens } from '../src/styles/color-tokens';
import { CONTRAST_PAIRS, checkContrast, contrastRatio } from '../src/styles/contrast';

let failed = false;

for (const mode of ['light', 'dark'] as const) {
  const tokens = Tokens[mode];
  const failures = checkContrast(tokens, mode);
  const ratios = CONTRAST_PAIRS.map((pair) => contrastRatio(pair.fg(tokens), pair.bg(tokens)));

  console.log(`\n[${mode}] 조합 ${CONTRAST_PAIRS.length}개, 최저 대비 ${Math.min(...ratios).toFixed(2)}`);

  for (const failure of failures) {
    const label = failure.excepted ? '예외' : '미달';
    console.log(`  ${label}  ${failure.name}  ${failure.ratio.toFixed(2)} (기준 ${failure.min})`);
  }

  if (failures.length === 0) console.log('  모두 통과');
  if (failures.some((failure) => !failure.excepted)) failed = true;
}

if (failed) {
  console.error('\n대비 기준에 못 미치는 조합이 있습니다.');
  process.exit(1);
}
