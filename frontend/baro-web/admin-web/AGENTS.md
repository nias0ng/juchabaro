# 주차바로 관리자 웹 개발 지침

이 문서는 사람과 AI가 동일한 구조와 기준으로 작업하기 위한 프로젝트 규칙이다.
새 기능을 구현하거나 기존 코드를 수정할 때 아래 규칙을 따른다.

## 기술 기준

- 이 프로젝트는 Vue 3(Composition API, `<script setup>`), Vite, TypeScript, Vue Router, Pinia를 사용한다.
- Options API 대신 `<script setup lang="ts">` 형식을 기본으로 작성한다.
- 데스크톱 브라우저(넓은 화면) 사용을 기준으로 하되, 태블릿 폭에서도 레이아웃이 깨지지 않게 작성한다.
- baro-app(모바일 앱)과 백엔드 API를 공유하므로, 요청/응답 형식은 백엔드 계약과 `frontend/baro-app`의 기존 타입 정의를 우선 참고한다.

## 작업 전 확인

- 작업 전에 관련 뷰, 컴포넌트, 스토어, 디자인 토큰을 먼저 검색한다.
- 이미 존재하는 공통 컴포넌트나 토큰을 중복해서 만들지 않는다.
- 현재 변경사항을 확인하고 다른 사람의 작업을 임의로 삭제하거나 되돌리지 않는다.
- 백엔드 API 형식이나 중요한 요구사항이 불분명하면 추측해서 확정하지 않는다.
- 새 패키지를 추가하기 전에 기존 의존성(Vue Router, Pinia)으로 해결할 수 있는지 확인한다.

## 폴더 구조

```text
src/
├─ router/              라우트 정의만 (경로 ↔ 뷰 매핑)
├─ views/                라우트에 연결되는 페이지. 얇게 유지하고 실제 로직은 features로 위임
├─ features/             기능 단위 코드 (api, components, composables, types)
├─ components/ui/        여러 기능에서 공유하는 UI
├─ stores/               Pinia 스토어 (전역 상태: 인증 등)
├─ services/             공통 API 클라이언트와 저장소
├─ composables/          앱 전체 공통 composable
└─ styles/               색상, 간격, 폰트, breakpoint 토큰과 전역 CSS
```

### `src/router`

- `router/index.ts`에는 경로 정의만 둔다. 화면 컴포넌트는 `component: () => import(...)`로 지연 로드한다.
- 인증이 필요한 경로는 `meta: { requiresAuth: true, role: 'ADMIN' }`처럼 라우트 메타데이터로 표시하고, 실제 검사는 `router.beforeEach` 네비게이션 가드 한 곳에서 처리한다.

### `src/views`

- 라우트 하나당 뷰 파일 하나를 원칙으로 한다.
- 뷰 파일에 비즈니스 로직, API 호출, 복잡한 마크업을 직접 쌓지 않는다. `features`의 컴포넌트/컴포저블을 조합하는 역할만 한다.

### `src/features`

- 기능별 코드는 `src/features/<feature>`에 둔다.
- 기능이 커질 때만 필요한 하위 폴더를 추가한다.

```text
features/parking-event/
├─ api/
├─ components/
├─ composables/
└─ types/
```

- 특정 기능에서만 쓰는 컴포넌트는 해당 기능의 `components`에 둔다.
- 여러 기능에서 실제로 공유되는 UI만 `src/components/ui`로 이동한다.
- 단순히 코드가 짧거나 비슷해 보인다는 이유만으로 성급하게 공통화하지 않는다.

## 파일과 이름 규칙

- `.vue` 컴포넌트 파일명은 `PascalCase`를 사용한다 (예: `ParkingEventListView.vue`).
- 그 외 TypeScript 파일(`.ts`)명은 `kebab-case`를 사용한다 (예: `parking-event-api.ts`).
- 컴포넌트와 타입 이름은 `PascalCase`를 사용한다.
- 함수, 변수, composable은 `camelCase`를 사용하고 composable은 `use`로 시작한다.
- Pinia 스토어는 `use<이름>Store` 형식으로 이름 짓는다 (예: `useAuthStore`).
- 라우트 뷰 파일명은 `*View.vue`로 작성한다.
- 기능 외부 파일을 import할 때는 `@/` 별칭을 사용한다.
- 같은 기능 안에서 가까운 파일을 import할 때는 상대 경로를 사용할 수 있다.
- `any` 사용을 피하고 API 요청·응답 및 컴포넌트 props 타입을 명시한다.

## 스타일 작성

- 컴포넌트 스타일은 `<style scoped>`를 기본으로 사용한다.
- 여러 컴포넌트에서 반복되는 값은 `src/styles`의 토큰(색상, 간격, 폰트, radius, breakpoint)을 CSS 변수 또는 TS 상수로 정의해 사용한다.
- `frontend/baro-app/src/styles`의 색상·간격·타이포그래피 값을 그대로 이식해 두 프로젝트의 톤을 맞추는 것을 우선 고려한다.

```css
/* 피한다 */
padding: 17px;
color: #5144d3;

/* 권장한다 */
padding: var(--spacing-md);
color: var(--color-primary);
```

- 전역 스타일(`src/assets/base.css`, `main.css`)에는 리셋과 CSS 변수 선언만 두고, 화면별 스타일은 각 컴포넌트의 `<style scoped>`에 둔다.
- 인라인 스타일(`:style` 바인딩)은 화면 크기나 상태에 따른 동적 값에만 제한적으로 사용한다.

## 반응형 레이아웃

- 관리자 웹은 데스크톱 우선이지만, 최소 태블릿 폭(768px 이상)에서 사이드바 + 콘텐츠 레이아웃이 유지되도록 작성한다.
- 화면마다 breakpoint 숫자를 직접 작성하지 않고 공통 토큰을 사용한다.
- 표(테이블) 형태의 데이터는 좁은 화면에서 가로 스크롤이 가능하도록 컨테이너를 감싼다.
- 사이드바, 헤더 같은 레이아웃 뼈대는 `App.vue` 또는 별도 `layouts/` 컴포넌트로 분리하고, 각 뷰는 콘텐츠 영역만 채운다.

## 공통 UI

- 새 UI를 만들기 전에 `src/components/ui`를 확인한다.
- 공통 컴포넌트는 특정 화면의 문구나 비즈니스 로직을 포함하지 않는다.
- 구조는 같고 색상이나 상태만 다른 컴포넌트는 복제보다 props(variant)를 검토한다.
- 공통 컴포넌트에 기능별 API 호출이나 라우팅을 직접 넣지 않는다.

## 인증 기능

- 인증 상태는 Pinia `useAuthStore`에서 최소 `loading`, `guest`, `authenticated`로 구분해 관리한다.
- 앱 시작 시 저장된 세션 복원이 끝나기 전에 라우트 접근을 확정하지 않는다.
- 인증·권한(ADMIN)이 필요한 라우트는 `router.beforeEach` 가드로 제한한다. 화면 컴포넌트 안에서 권한을 판단하지 않는다.
- 로그인 화면에서 API와 저장소를 직접 조작하지 않는다.
  - 화면은 사용자 입력과 상태 표시를 담당한다.
  - API 호출은 `features/auth/api`에 둔다.
  - 로그인·로그아웃 흐름과 세션 상태는 `stores/auth-store.ts`가 담당한다.
- 비밀번호, Access Token, 개인정보를 로그에 출력하지 않는다.
- 토큰을 소스 코드나 `VITE_` 접두사 환경 변수에 저장하지 않는다.
- 로그인 요청 중에는 중복 제출을 막고 로딩 상태를 표시한다.
- 서버 오류와 입력 검증 오류를 구분하여 사용자에게 표시한다.

## 상태와 API 처리

- 서버 상태, 전역 앱 상태, 화면 로컬 상태를 구분한다.
- 한 화면에서만 쓰는 입력값과 UI 상태는 `ref`/`reactive`로 화면 또는 기능 composable에 둔다.
- 여러 화면이 공유하는 상태(로그인 사용자, 세션 등)만 Pinia 스토어로 관리한다. 화면 하나에서만 쓰는 상태를 스토어로 만들지 않는다.
- API 주소, 요청 필드, 응답 타입, 오류 형식을 백엔드 계약에 맞춰 작성한다.
- API 응답을 화면에서 바로 임의 변환하지 말고 기능 API 또는 mapper에서 처리한다.
- 모든 비동기 화면은 필요한 경우 다음 상태를 고려한다.
  - loading
  - success
  - empty
  - error

## 환경 변수

- Vite는 `VITE_` 접두사가 붙은 환경 변수만 클라이언트 번들에 포함한다. 민감하지 않은 값(서버 주소 등)에만 사용한다.
- 실제 값은 `.env.local`(git에 커밋하지 않음)에 두고, `.env.example`에는 플레이스홀더만 남긴다.
- 환경 변수를 새로 추가하거나 값을 바꾸면 개발 서버를 재시작해야 반영된다.
- `import.meta.env.VITE_*`를 타입 체크하려면 `env.d.ts`에 선언을 추가한다.

## 목(mock) 데이터

- 백엔드 API가 아직 없는 기능(관리자 사건 조회/상태 변경, 반복 위반 조회 등)은 `<feature>-api.mock.ts`에 목 구현을 두고, `import.meta.env.DEV && import.meta.env.VITE_USE_MOCK_*==='true'` 조건으로 실제 API 호출과 분기한다.
- 목 모드 조건에는 반드시 `import.meta.env.DEV`를 함께 써서 프로덕션 빌드에서 자동으로 꺼지게 한다.
- 실제 API가 준비되면 목 파일과 분기 코드, 관련 환경 변수를 정리한다.

## 저장소 사용 구분

- 브라우저에는 `expo-secure-store` 같은 OS 수준 암호화 저장소가 없다. accessToken은 우선 메모리(Pinia 스토어)에 보관하고, 새로고침 후에도 로그인을 유지해야 하면 `sessionStorage`를 사용한다. `localStorage`에 토큰을 저장하지 않는다(XSS 노출 범위가 더 넓음).
- 장기적으로는 백엔드에 httpOnly 쿠키 발급을 요청하는 방식으로 전환하는 것을 검토한다. 그 전까지는 XSS 방어(사용자 입력 sanitize, `v-html` 최소 사용)를 더 엄격히 지킨다.
- 화면이나 컴포넌트에서 `sessionStorage`/`localStorage`를 직접 호출하지 않고, `services/session-storage.ts`로 감싼 함수만 사용한다.

## API 클라이언트 구조

- 모든 API 호출은 `services/http-client.ts`의 공통 요청 함수를 거친다. 이 파일이 백엔드 공통 응답 포맷(`httpStatus`/`isSuccess`/`message`/`code`/`result`)을 해석하고 실패를 `ApiError`(`services/api-error.ts`)로 변환한다. (`frontend/baro-app/src/services/http-client.ts`와 동일한 포맷을 다룬다.)
- 기능별 API 파일(`features/<기능>/api/*.ts`)은 이 공통 함수를 부르는 얇은 함수와 요청/응답 타입만 둔다. `fetch`를 직접 호출하지 않는다.
- 새 서비스(사건, 주차 구역 등) API를 추가할 때도 이 구조를 그대로 따른다.

## 주석

- 모든 파일이나 모든 함수에 설명 주석을 의무적으로 작성하지 않는다.
- 파일명, 타입, 함수명으로 알 수 있는 내용을 그대로 반복하지 않는다.
- 주석은 코드가 무엇을 하는지보다 왜 그렇게 동작해야 하는지를 설명한다.
- 다음 경우에는 짧은 주석이나 JSDoc을 작성한다.
  - 복잡한 비즈니스 규칙
  - 인증과 보안 처리
  - 재사용되는 스토어, 서비스, composable의 비명시적 동작
  - 임시 우회 코드의 제거 조건
- `TODO`에는 가능한 경우 이슈 번호와 제거 조건을 기록한다.

```ts
// TODO(#123): 백엔드 /admin/parking-events가 배포되면 mock 분기를 제거한다.
```

## 접근성과 사용자 경험

- 클릭 가능한 요소에는 적절한 시맨틱 태그(`button`, `a`)와 `aria-*` 속성을 제공한다.
- 색상만으로 상태를 구분하지 않는다(뱃지에 아이콘·텍스트 병행).
- 표 형태 데이터는 키보드 탐색과 스크린 리더를 고려해 `<table>` 시맨틱 또는 적절한 role을 사용한다.
- 로딩 중인 버튼은 중복 입력을 막고 진행 상태를 전달한다.
- 오류 메시지는 사용자가 다음 행동을 이해할 수 있게 작성한다.

## 검증

- 변경 후 최소한 다음 명령을 실행한다.

```powershell
npm run type-check
npm run lint
```

- 라우트나 레이아웃 구조를 변경하면 실제로 페이지를 열어 새로고침·직접 URL 진입 시 문제가 없는지 확인한다(SPA 라우팅 특성상 새로고침 시 404가 날 수 있는 배포 설정도 함께 점검한다).
- 넓은 화면과 태블릿 폭 모두에서 레이아웃을 확인한다.
- 검증하지 못한 항목이 있으면 완료 보고에 이유를 명시한다.

## 작업 완료 기준

- 요구한 기능이 실제로 동작한다.
- 기존 공통 컴포넌트와 토큰을 재사용했다.
- 불필요한 중복과 매직 넘버를 추가하지 않았다.
- 로딩, 오류, 비어 있는 상태를 필요한 범위에서 처리했다.
- TypeScript 오류가 없다.
- 관련 린트가 통과했거나 실행하지 못한 이유가 기록되어 있다.
- 임시 파일, 디버그 로그, 민감한 정보가 남아 있지 않다.
- 변경한 파일과 검증 결과를 사용자에게 간단히 설명한다.
