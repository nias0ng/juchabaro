# 주차바로 관리자 웹 입문 가이드

코드를 수정하기 전에 한 번 읽고, 새로운 기능을 만들 때는 마지막의 체크리스트를 확인해주세요.

이 문서는 `frontend/baro-web/admin-web`(관리자 웹) 프로젝트를 다룹니다. 모바일 앱(`frontend/baro-app`)은 React Native/Expo를 쓰지만, 관리자 웹은 **Vue 3**를 사용합니다. 두 프로젝트는 같은 백엔드 API를 공유하므로 데이터 모델과 API 규칙은 `frontend/baro-app`의 `FRONTEND_GUIDE.md`도 함께 참고하면 도움이 됩니다.

---

## 1. 먼저 알아둘 개념

### Vue 3

HTML, CSS, JavaScript(TypeScript)를 하나의 파일로 묶어 화면을 구성하는 프레임워크입니다. React의 컴포넌트와 비슷한 역할을 합니다.

```vue
<script setup lang="ts">
const message = '안녕하세요';
</script>

<template>
  <div>
    <p>{{ message }}</p>
    <button @click="message = '클릭됨'">확인</button>
  </div>
</template>
```

### SFC(Single File Component)

위 예시처럼 `<script>`, `<template>`, `<style>`을 한 파일(`.vue`)에 모아 작성하는 방식을 SFC라고 합니다.

### `<script setup>`

Vue 3의 Composition API를 가장 간결하게 쓰는 문법입니다. React의 함수형 컴포넌트 + Hook과 비슷한 위치에 있습니다.

```vue
<script setup lang="ts">
import { ref } from 'vue';

const count = ref(0);
</script>

<template>
  <button @click="count++">{{ count }}</button>
</template>
```

- `ref(초기값)`은 React의 `useState`와 비슷하게, 값이 바뀌면 화면이 다시 그려지게 합니다.
- 템플릿에서는 `.value` 없이 바로 `count`로 접근할 수 있습니다(스크립트 안에서는 `count.value`).

### Vite

빠른 개발 서버와 빌드 도구입니다. `npm run dev`로 실행하면 코드 저장 즉시 브라우저에 반영됩니다(HMR).

### Vue Router

주소(URL)에 따라 어떤 화면을 보여줄지 정하는 라이브러리입니다. Expo Router와 달리 파일 위치가 아니라 `src/router/index.ts`에 경로를 직접 정의합니다.

```ts
{
  path: '/events/:eventId',
  name: 'event-detail',
  component: () => import('../views/ParkingEventDetailView.vue'),
}
```

### Pinia

여러 화면이 함께 쓰는 상태(로그인 사용자 정보 등)를 관리하는 라이브러리입니다. React의 Context/Provider가 하던 역할을 담당합니다.

```ts
// stores/auth-store.ts
export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserProfile | null>(null);
  return { user };
});
```

### Composable

컴포넌트 여러 개에서 재사용할 상태나 로직을 함수로 뽑아낸 것입니다. React의 커스텀 Hook과 정확히 같은 개념이며, 이름은 `use`로 시작합니다.

```ts
export function useCountdown(dueAt: string) {
  const remaining = ref(0);
  // ...
  return { remaining };
}
```

### Props와 상태

- `props`: 부모가 컴포넌트에 전달하는 값
- 컴포넌트 내부 상태: `ref`/`reactive`로 선언

```vue
<script setup lang="ts">
defineProps<{ name: string }>();
</script>

<template>
  <p>{{ name }}님, 안녕하세요.</p>
</template>
```

---

## 2. 현재 파일 구조

```text
src/
├─ router/
│  └─ index.ts                     # 경로 ↔ 뷰 매핑
├─ views/                          # 라우트에 연결되는 페이지
│  ├─ LoginView.vue                # /login
│  ├─ DashboardView.vue            # /home (← "/"는 /home으로 리다이렉트)
│  ├─ ParkingEventListView.vue     # /events
│  ├─ ParkingEventDetailView.vue   # /events/:eventId
│  ├─ ParkingZoneManagementView.vue# /parking-zones
│  ├─ HistoryView.vue              # /history
│  └─ SettingsView.vue             # /settings
├─ App.vue                         # 전체 레이아웃(임시 네비게이션 포함)
├─ main.ts                         # 앱 진입점 (Pinia, Router 등록)
│
├─ features/                       # (앞으로 추가될) 기능별 코드
├─ components/ui/                  # (앞으로 추가될) 공유 UI
├─ stores/                         # (앞으로 추가될) Pinia 스토어
├─ services/                       # (앞으로 추가될) 공통 API 클라이언트
└─ styles/                         # (앞으로 추가될) 디자인 토큰
```

`features`, `components/ui`, `stores`, `services`, `styles`는 아직 실제 파일이 없는 예정 구조입니다. 화면을 만들면서 필요할 때 채워나갑니다. 자세한 규칙은 [`admin-web/AGENTS.md`](admin-web/AGENTS.md)를 참고하세요.

### 왜 `views`를 얇게 유지하나요?

`views`의 컴포넌트가 API 호출, 상태 관리, 복잡한 마크업을 전부 떠안으면 파일이 금방 비대해집니다. `baro-app`이 `app/`(라우트)과 `features/`(실제 로직)를 나누듯, 관리자 웹도 `views/`는 페이지 뼈대만 담당하고 실제 기능은 `features/<기능>`에 작성합니다.

```vue
<!-- views/ParkingEventListView.vue -->
<script setup lang="ts">
import ParkingEventTable from '@/features/parking-event/components/ParkingEventTable.vue';
</script>

<template>
  <ParkingEventTable />
</template>
```

---

## 3. 스타일 작성하기

### `<style scoped>`

컴포넌트 파일 안에 CSS를 그대로 작성할 수 있습니다. `scoped`를 붙이면 이 스타일이 해당 컴포넌트에만 적용됩니다.

```vue
<style scoped>
.card {
  padding: 16px;
  border-radius: 12px;
}
</style>
```

### 값을 직접 쓰지 않는 이유

화면마다 색상과 간격 숫자를 따로 적으면 디자인을 한 번에 바꾸기 어렵습니다. `baro-app`처럼 공통 토큰을 CSS 변수나 TS 상수로 만들어 재사용합니다.

```css
/* 피하는 방식 */
padding: 17px;
color: #5144d3;

/* 권장하는 방식 */
padding: var(--spacing-md);
color: var(--color-primary);
```

### 전역 스타일은 언제 쓰나요?

`src/assets/base.css`, `main.css`에는 브라우저 기본 리셋과 CSS 변수 선언만 둡니다. 화면 각각의 스타일은 그 컴포넌트의 `<style scoped>`에 작성합니다.

---

## 4. 반응형 레이아웃

관리자 웹은 데스크톱에서 주로 사용하지만, 태블릿 폭에서도 사이드바 + 콘텐츠 구조가 무너지지 않아야 합니다.

- 표(테이블) 데이터는 좁은 화면에서 가로 스크롤이 가능한 컨테이너로 감쌉니다.
- breakpoint 숫자를 화면마다 새로 적지 않고, 공통 토큰(추가 예정)을 사용합니다.
- 사이드바·헤더 같은 레이아웃 뼈대는 `App.vue`(또는 향후 `layouts/`)에서 한 번만 정의하고, 각 뷰는 콘텐츠 영역만 채웁니다.

---

## 5. 공통 UI 컴포넌트

아직 `components/ui`에 실제 컴포넌트는 없습니다. 새 화면을 만들 때 버튼, 카드, 뱃지처럼 여러 화면에서 반복되는 UI가 생기면 이곳으로 옮깁니다.

### 어디까지 공통으로 만들어야 하나요?

```text
여러 화면에서 쓰는 버튼
→ components/ui/AppButton.vue

사건 목록에서만 쓰는 상태 뱃지
→ features/parking-event/components/EventStatusBadge.vue

사건 목록 화면 전체
→ views/ParkingEventListView.vue (얇게) + features/parking-event/...
```

공통 UI 안에는 특정 기능의 API 호출이나 라우팅을 직접 넣지 않습니다.

---

## 6. ESLint / oxlint란?

코드를 실행하기 전에 문제 가능성이 있는 코드를 찾아주는 검사 도구입니다. 이 프로젝트는 `eslint`와 `oxlint`를 함께 사용합니다(`oxlint`가 더 빠르게 일부 규칙을 먼저 검사합니다).

### 실행 방법

```powershell
cd frontend\baro-web\admin-web
npm run lint
```

자동 수정 가능한 문제까지 고치려면 다음을 사용합니다(이미 `lint` 스크립트에 `--fix`가 포함되어 있습니다).

```powershell
npm run lint
```

### 규칙을 끄면 안 되나요?

오류가 난다는 이유만으로 규칙을 프로젝트 전체에서 끄지 않습니다. 정말 예외가 필요한 경우에만 이유를 적고 최소 범위에서 비활성화합니다.

---

## 7. TypeScript 검사

```powershell
cd frontend\baro-web\admin-web
npm run type-check
```

`vue-tsc`가 `.vue` 파일의 `<script>`까지 포함해 타입을 검사합니다. 다음과 같은 문제를 찾습니다.

- 잘못된 타입 전달
- 존재하지 않는 속성 접근
- 필수 props 누락
- API 응답 타입 불일치

기능 작업이 끝나면 lint와 type-check를 모두 실행합니다.

```powershell
npm run type-check
npm run lint
```

---

## 8. 주석은 어떻게 작성하나요?

코드가 무엇을 하는지는 이름으로 표현하고, 주석은 **왜 이렇게 작성했는지**를 설명합니다.

```ts
// 좋지 않은 주석
// 로그인 버튼을 누르면 로그인한다.
await login();

// 좋은 주석
// 세션 복원 중에는 로그인 여부를 확정할 수 없어 라우트 이동을 보류한다.
if (status.value === 'loading') {
  return;
}
```

`TODO`에는 가능하면 이슈 번호나 제거 조건을 작성합니다.

```ts
// TODO(#123): 백엔드 /admin/parking-events가 배포되면 mock 분기를 제거한다.
```

---

## 9. 새로운 화면을 만드는 순서

예를 들어 "반복 위반 차량 상세" 화면을 만든다고 가정합니다.

### 1단계: 라우트 추가하기

```ts
// src/router/index.ts
{
  path: '/repeat-violations/:vehicleId',
  name: 'repeat-violation-detail',
  component: () => import('../views/RepeatViolationDetailView.vue'),
}
```

### 2단계: 뷰 파일 만들기

```vue
<!-- src/views/RepeatViolationDetailView.vue -->
<script setup lang="ts">
import { useRoute } from 'vue-router';

const route = useRoute();
const vehicleId = route.params.vehicleId;
</script>

<template>
  <section>
    <h1>반복 위반 상세 ({{ vehicleId }})</h1>
  </section>
</template>
```

### 3단계: 실제 기능 채우기

API 호출, 표, 필터 같은 실제 내용은 `features/repeat-violation/` 아래에 작성하고 뷰에서 조합합니다.

### 4단계: 주소 확인하기

```text
http://localhost:5174/repeat-violations/123
```

### 5단계: 검사하기

```powershell
npm run type-check
npm run lint
```

---

## 10. 환경 변수 이해하기

### `VITE_` 접두사

Vite는 `VITE_`로 시작하는 환경 변수만 클라이언트 번들에 포함시킵니다(Expo의 `EXPO_PUBLIC_`과 같은 역할).

```text
VITE_API_BASE_URL=http://localhost:8080
```

### `.env.local`과 `.env.example`

- `.env.local`: 실제 값. git에 커밋되지 않습니다.
- `.env.example`: 어떤 값이 필요한지 보여주는 견본.

```powershell
cd frontend\baro-web\admin-web
copy .env.example .env.local
```

### 값을 바꿨는데 반영이 안 돼요

환경 변수를 바꾼 뒤에는 실행 중인 개발 서버를 껐다가 다시 켜야 합니다.

### 타입 체크가 되게 하려면

`import.meta.env.VITE_API_BASE_URL`처럼 새 환경 변수를 쓰려면 `env.d.ts`에 선언을 추가합니다.

```ts
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
}
```

---

## 11. 목(mock) 데이터로 개발하기

백엔드 API가 아직 배포되지 않은 기능(예: 관리자 사건 조회, 반복 위반 조회)은 목 데이터로 화면을 먼저 만들 수 있습니다.

```ts
// parking-event-api.mock.ts
export async function getParkingEventsMock(): Promise<ParkingEventListResult> {
  await delay(500);
  return { events: [/* ... */], totalCount: 0 };
}
```

```ts
// parking-event-api.ts
const useMock = import.meta.env.DEV && import.meta.env.VITE_USE_MOCK_PARKING_EVENT === 'true';

export function getParkingEvents(): Promise<ParkingEventListResult> {
  if (useMock) return getParkingEventsMock();
  return getJson<ParkingEventListResult>('/api/admin/parking-events');
}
```

`import.meta.env.DEV`는 개발 모드에서만 `true`입니다. 이 조건이 없으면 실수로 목 모드가 켜진 채 배포될 위험이 있습니다.

실제 API가 준비되면 목 파일과 분기 코드, 관련 환경 변수를 정리합니다.

---

## 12. 토큰과 민감한 값은 어디에 저장하나요?

모바일 앱은 `expo-secure-store`라는 OS 암호화 저장소를 쓸 수 있지만, **브라우저에는 그런 저장소가 없습니다.**

| 저장 방식 | 특징 | 비고 |
| --- | --- | --- |
| 메모리(Pinia 스토어) | 새로고침하면 사라짐 | 가장 안전. 기본으로 우선 고려 |
| `sessionStorage` | 탭을 닫으면 사라짐 | 새로고침 유지가 필요할 때 |
| `localStorage` | 영구 저장 | 토큰 저장에는 권장하지 않음(XSS 노출 범위가 큼) |
| httpOnly 쿠키 | JS로 접근 불가, 가장 안전 | 백엔드가 쿠키 발급을 지원해야 함(현재 미지원) |

지금은 백엔드가 JWT를 응답 본문으로만 내려주므로 httpOnly 쿠키를 바로 쓸 수 없습니다. 우선 메모리/`sessionStorage` 조합으로 시작하고, 화면이나 컴포넌트에서 직접 호출하지 않고 `services/session-storage.ts`로 감싼 함수만 사용합니다.

---

## 13. API 호출은 어떻게 구조화하나요?

`baro-app`과 동일한 응답 포맷(`httpStatus`, `isSuccess`, `message`, `code`, `result`)을 쓰는 백엔드를 그대로 공유합니다.

```text
화면 (views/ParkingEventListView.vue)
  → 기능 컴포넌트/composable (features/parking-event/...)
    → API 함수 (features/parking-event/api/parking-event-api.ts)
      → 공통 클라이언트 (services/http-client.ts)
        → fetch()
```

### `services/http-client.ts`가 하는 일

응답 포맷을 해석하고 실패를 `ApiError`로 변환하는 로직을 한 곳에만 둡니다(`frontend/baro-app/src/services/http-client.ts`를 그대로 이식하는 것을 권장합니다).

```ts
if (!response.ok || !body?.isSuccess) {
  throw new ApiError(body?.message ?? '요청을 처리하지 못했습니다.', response.status, body?.code);
}
return body.result;
```

### `features/<기능>/api/*.ts`가 하는 일

"어떤 주소에 뭘 보내는지"만 담당합니다.

```ts
export function getParkingEvents(): Promise<ParkingEventListResult> {
  return getJson<ParkingEventListResult>('/api/admin/parking-events');
}
```

---

## 14. AI를 사용할 때 지켜야 할 규칙

AI에게 작업을 요청할 때는 다음 내용을 함께 전달합니다.

1. 먼저 `admin-web/AGENTS.md`를 읽을 것
2. 기존 공통 컴포넌트와 스타일 토큰을 확인할 것
3. `src/views`는 얇게 유지하고, 실제 기능은 `src/features`에 작성할 것
4. `<script setup lang="ts">`를 사용할 것
5. 임의의 고정 너비와 색상값을 피할 것
6. 작업 후 type-check와 lint를 실행할 것
7. 기존 코드를 임의로 삭제하지 않을 것

AI가 작성한 코드도 반드시 사람이 확인해야 합니다. 특히 다음 항목을 확인합니다.

- API 주소와 필드가 실제 백엔드 계약과 같은가?
- 보안 정보(토큰 등)가 로그나 `localStorage`에 안전하지 않게 남아 있지 않은가?
- 기존 공통 컴포넌트를 중복해서 만들지 않았는가?
- 태블릿 폭에서 레이아웃이 깨지지 않는가?

---

## 15. 기본 작업 순서

```text
1. 관련 파일과 공통 컴포넌트 확인
2. 백엔드 API 계약 확인 (admin-service 엔드포인트는 아직 미구현일 수 있음 → mock 필요 여부 판단)
3. 라우트/뷰 추가
4. 기능 구현 (features/)
5. 데스크톱과 태블릿 폭 확인
6. TypeScript 검사
7. ESLint/oxlint 검사
8. 불필요한 로그와 임시 코드 제거
9. 커밋 또는 Merge Request
```

```powershell
cd frontend\baro-web\admin-web
npm run type-check
npm run lint
```

---

## 16. 작업 완료 체크리스트

### 구조

- [ ] `src/views`에는 페이지 뼈대만 있는가?
- [ ] 실제 기능은 올바른 `features` 폴더에 있는가?
- [ ] 기존 공통 컴포넌트를 먼저 확인했는가?

### 스타일

- [ ] 색상과 간격에 공통 토큰을 사용했는가?
- [ ] 불필요한 고정 너비를 사용하지 않았는가?
- [ ] 태블릿 폭에서 레이아웃이 깨지지 않는가?
- [ ] 표 형태 데이터가 좁은 화면에서 가로 스크롤되는가?

### 기능

- [ ] 로딩 상태를 처리했는가?
- [ ] 오류 상태를 처리했는가?
- [ ] 버튼 중복 제출을 막았는가?
- [ ] 개인정보와 토큰을 로그에 출력하지 않았는가?

### API·저장소

- [ ] API 호출이 `services/http-client.ts`를 거치는가? (`fetch`를 직접 부르지 않았는가?)
- [ ] 목 데이터를 쓴다면 `import.meta.env.DEV` 조건과 함께 분기했는가?
- [ ] 토큰을 `localStorage`에 저장하지 않았는가?
- [ ] 새 환경 변수를 추가했다면 `.env.example`과 `env.d.ts`도 같이 갱신했는가?

### 검증

- [ ] `npm run type-check`가 통과하는가?
- [ ] `npm run lint`가 통과하는가?
- [ ] 디버그용 `console.log`가 남아 있지 않은가?
- [ ] 변경한 화면을 직접 실행해 확인했는가?
