// Node에서 src의 TypeScript 파일을 번들러 없이 직접 불러오기 위한 resolve 훅.
// 앱 코드는 확장자 없는 import와 `@/` 별칭을 쓰는데, Node의 ESM 해석은 둘 다 지원하지 않는다.
import { existsSync } from 'node:fs';
import { registerHooks } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const srcDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'src');
const CANDIDATES = ['', '.ts', '.tsx', '/index.ts'];

function resolveFile(basePath) {
  for (const suffix of CANDIDATES) {
    const candidate = basePath + suffix;
    if (existsSync(candidate) && path.extname(candidate) !== '') return candidate;
  }
  return null;
}

registerHooks({
  resolve(specifier, context, nextResolve) {
    let basePath = null;

    if (specifier.startsWith('@/')) {
      basePath = path.join(srcDir, specifier.slice(2));
    } else if (specifier.startsWith('.') && context.parentURL?.startsWith('file:')) {
      basePath = path.resolve(path.dirname(fileURLToPath(context.parentURL)), specifier);
    }

    const resolved = basePath ? resolveFile(basePath) : null;
    if (resolved) {
      return nextResolve(pathToFileURL(resolved).href, context);
    }
    return nextResolve(specifier, context);
  },
});
