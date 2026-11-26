// 색을 쓰는 방식별 사용 횟수를 센다. 디자인 토큰 이전의 전후 비교에 쓴다.
// 사용법: node scripts/count-color-usage.mjs [경로 ...]   (기본: src)
// src/styles(토큰 정의)와 테스트 파일은 세지 않는다.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

const targets = process.argv.slice(2).length > 0 ? process.argv.slice(2) : ['src'];
const EXCLUDED_DIR = path.normalize('src/styles');

const PATTERNS = {
  'theme.* (기존 의미 토큰)': /\btheme\.[a-zA-Z]+\b/g,
  'Palette.* 직접 사용': /\bPalette\.[a-zA-Z0-9]+\b/g,
  '색상 값 하드코딩': /(['"`])(#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})|(?:rgb|hsl)a?\([^)]*\))\1/g,
};

function collectFiles(target) {
  const stat = statSync(target);
  if (stat.isFile()) return [target];
  return readdirSync(target).flatMap((name) => collectFiles(path.join(target, name)));
}

const files = targets
  .flatMap(collectFiles)
  .filter((file) => /\.(ts|tsx)$/.test(file) && !/\.test\.ts$/.test(file))
  .filter((file) => !path.normalize(file).startsWith(EXCLUDED_DIR));

const totals = Object.fromEntries(
  Object.keys(PATTERNS).map((name) => [name, { occurrences: 0, lines: 0, files: 0 }]),
);

for (const file of files) {
  const lines = readFileSync(file, 'utf8').split('\n');
  const seen = new Set();

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) continue;

    for (const [name, pattern] of Object.entries(PATTERNS)) {
      const count = (line.match(pattern) ?? []).length;
      if (count === 0) continue;
      totals[name].occurrences += count;
      totals[name].lines += 1;
      seen.add(name);
    }
  }

  for (const name of seen) totals[name].files += 1;
}

console.log(`대상: ${targets.join(', ')} (파일 ${files.length}개, src/styles 제외)`);
console.table(totals);
