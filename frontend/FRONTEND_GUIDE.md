# 주차바로 프런트엔드 입문 가이드

코드를 수정하기 전에 한 번 읽고, 새로운 기능을 만들 때는 마지막의 체크리스트를 확인해주세요.

---

## 1. 먼저 알아둘 개념

### React Native

JavaScript와 React를 사용해 Android, iOS 앱을 만드는 기술입니다.

웹의 `<div>`, `<button>`, `<p>` 대신 다음과 같은 React Native 컴포넌트를 사용합니다.

```tsx
import { Pressable, Text, View } from 'react-native';

<View>
  <Text>안녕하세요</Text>
  <Pressable>
    <Text>확인</Text>
  </Pressable>
</View>
```

### Expo

React Native 앱의 실행, 빌드, 라이브러리 연결을 편하게 도와주는 도구입니다.

이 프로젝트는 **Expo SDK 57**을 사용합니다.

### Expo Router

파일 위치를 기준으로 화면 주소를 만들어주는 라우터입니다.

```text
src/app/auth/login.tsx
→ /auth/login

src/app/resident/vehicles.tsx
→ /resident/vehicles
```

따라서 `src/app`에는 경로와 관련된 파일만 두어야 합니다.

### 컴포넌트

화면을 구성하는 재사용 가능한 UI 조각입니다.

예를 들어 버튼을 화면마다 새로 만드는 대신 `AppButton`을 만들어 여러 화면에서 사용할 수 있습니다.

### Props와 State

- `props`: 부모가 컴포넌트에 전달하는 값
- `state`: 컴포넌트 내부에서 변경되는 값

```tsx
type GreetingProps = {
  name: string;
};

function Greeting({ name }: GreetingProps) {
  return <Text>{name}님, 안녕하세요.</Text>;
}
```

### Hook

컴포넌트에서 상태나 공통 로직을 사용하게 해주는 함수입니다.

Hook의 이름은 `use`로 시작합니다.

```tsx
const { width } = useWindowDimensions();
```

---

## 2. 현재 파일 구조

```text
src/
├─ app/                           # Expo Router 경로만 배치
│  ├─ _layout.tsx                 # 앱 전체 화면 구조
│  ├─ index.tsx                   # /
│  ├─ auth/
│  │  ├─ _layout.tsx
│  │  ├─ index.tsx                # /auth
│  │  ├─ login.tsx                # /auth/login
│  │  └─ signup.tsx               # /auth/signup
│  └─ resident/
│     ├─ _layout.tsx
│     ├─ index.tsx                # /resident
│     ├─ notifications.tsx
│     ├─ vehicles.tsx
│     └─ my-page.tsx
│
├─ features/                      # 실제 기능과 화면
│  ├─ auth/
│  │  └─ screens/
│  │     ├─ auth-welcome-screen.tsx
│  │     ├─ auth-welcome-screen.styles.ts
│  │     ├─ login-screen.tsx
│  │     └─ signup-screen.tsx
│  └─ resident/
│     └─ screens/
│        ├─ home-screen.tsx
│        ├─ notifications-screen.tsx
│        ├─ vehicles-screen.tsx
│        └─ my-page-screen.tsx
│
├─ components/
│  └─ ui/                         # 여러 기능에서 사용하는 공통 UI
│     ├─ app-button.tsx
│     ├─ responsive-container.tsx
│     ├─ screen.tsx
│     ├─ stack.tsx
│     ├─ themed-text.tsx
│     └─ themed-view.tsx
│
├─ hooks/                         # 앱 전체에서 사용하는 공통 Hook
│
└─ styles/                        # 전역 디자인 시스템
   ├─ colors.ts                   # 색상과 라이트/다크 테마
   ├─ spacing.ts                  # 간격과 border radius
   ├─ typography.ts               # 폰트 크기, 굵기, 줄 높이
   ├─ layout.ts                   # breakpoint, 최대 폭, 버튼 높이
   ├─ global.css                  # 브라우저 전용 전역 CSS
   └─ index.ts                    # 스타일 통합 export
```

### 왜 `app`과 `features`를 나누나요?

`src/app`은 Expo Router가 읽는 특별한 폴더입니다.

`src/app` 밑에 일반 컴포넌트나 스타일 파일을 두면 Expo Router가 그것도 URL 경로로 인식할 수 있습니다.

따라서 라우트 파일은 다음처럼 실제 화면을 연결하는 역할만 하도록 얇게 유지합니다.

```tsx
// src/app/auth/login.tsx
export { default } from '@/features/auth/screens/login-screen';
```

실제 로그인 화면은 아래에 작성합니다.

```text
src/features/auth/screens/login-screen.tsx
```

### 기능이 커지면 어떻게 하나요?

필요할 때 기능 폴더 안에 다음 폴더를 추가합니다.

```text
features/auth/
├─ api/             # 로그인·로그아웃 API
├─ components/      # LoginForm 등 인증 전용 컴포넌트
├─ hooks/           # useLogin, useLogout
├─ screens/         # 인증 화면
├─ types/           # 요청·응답 타입
└─ validation/      # 입력값 검사
```

아직 필요하지 않은 빈 폴더는 미리 만들지 않습니다.

---

## 3. 스타일 파일 이해하기

### `.styles.ts`는 CSS 파일인가요?

CSS와 **같은 역할**을 하지만 실제 CSS 문법은 아닙니다.

React Native의 `StyleSheet`를 사용하는 TypeScript 파일입니다.

```ts
// login-screen.styles.ts
import { StyleSheet } from 'react-native';

import { Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: Spacing.lg,
  },
});
```

화면에서는 다음처럼 가져옵니다.

```tsx
import { styles } from './login-screen.styles';

<View style={styles.container} />
```

### 모든 화면에 `.styles.ts`가 필요한가요?

아닙니다.

로컬 스타일이 있을 때만 만듭니다.

```text
로컬 스타일 있음
├─ auth-welcome-screen.tsx
└─ auth-welcome-screen.styles.ts

로컬 스타일 없음
└─ login-screen.tsx
```

`Stack`, `Spacing`, `ResponsiveContainer`만으로 충분하면 빈 스타일 파일을 만들지 않습니다.

### 색상과 여백을 직접 작성하지 않는 이유

다음처럼 화면마다 다른 숫자와 색상을 작성하면 디자인을 한 번에 바꾸기 어렵습니다.

```ts
// 피하는 방식
padding: 17,
color: '#5144d3',
```

공통 토큰을 사용하면 전체 디자인을 한 곳에서 관리할 수 있습니다.

```ts
// 권장 방식
padding: Spacing.md,
color: theme.primary,
```

공통 스타일은 아래처럼 가져옵니다.

```tsx
import {
  Breakpoints,
  Colors,
  FontSize,
  Radius,
  Spacing,
} from '@/styles';
```

### `global.css`는 언제 사용하나요?

`global.css`는 브라우저 전용입니다.

다음과 같은 웹 전체 설정에만 사용합니다.

- `html`, `body`
- 브라우저 기본 여백 제거
- CSS 변수
- 웹 폰트

Android와 iOS 화면 스타일은 `StyleSheet`를 사용합니다.

---

## 4. Flex와 반응형 UI

React Native의 레이아웃은 대부분 Flexbox를 사용합니다.

웹과 달리 기본 방향은 세로입니다.

```ts
flexDirection: 'column'
```

### 기본 화면 구조

일반 화면은 가능하면 다음 구조를 사용합니다.

```tsx
<Screen scroll>
  <ResponsiveContainer>
    <Stack gap={Spacing.md}>
      {/* 화면 내용 */}
    </Stack>
  </ResponsiveContainer>
</Screen>
```

각 컴포넌트의 역할은 다음과 같습니다.

- `Screen`: Safe Area와 스크롤 처리
- `ResponsiveContainer`: 좌우 여백과 최대 콘텐츠 폭
- `Stack`: 세로 또는 가로 Flex 배치

### 자주 사용하는 Flex 속성

```ts
{
  flex: 1,                 // 남은 공간을 채움
  flexDirection: 'row',    // 자식 요소를 가로로 배치
  alignItems: 'center',    // 교차 방향 정렬
  justifyContent: 'center',// 진행 방향 정렬
  gap: Spacing.md,         // 자식 사이 간격
  width: '100%',           // 부모 너비 사용
}
```

### 반응형 작성 방법

작은 화면과 넓은 화면에서 구조가 달라져야 할 때 `useWindowDimensions`를 사용합니다.

```tsx
const { width } = useWindowDimensions();
const isWide = width >= Breakpoints.tablet;

<Stack direction={isWide ? 'row' : 'column'} />
```

화면마다 `768` 같은 값을 직접 작성하지 않고 `Breakpoints`를 사용합니다.

### 고정 숫자는 전부 나쁜가요?

아닙니다.

다음 값은 공통 토큰이나 명확한 이유가 있으면 고정값을 사용할 수 있습니다.

- 버튼의 최소 높이
- 아이콘 크기
- 폰트 크기
- 테두리 두께
- 콘텐츠 최대 폭
- 이미지 비율
- 그림자와 애니메이션 값

화면 전체나 주요 카드의 너비를 임의의 숫자로 고정하는 것은 피합니다.

```ts
// 피하는 방식
width: 318,

// 권장 방식
width: '100%',
maxWidth: ContentWidth.compact,
aspectRatio: 1,
```

---

## 5. 공통 UI 컴포넌트

새 UI를 만들기 전에 `src/components/ui`를 먼저 확인합니다.

### 현재 공통 컴포넌트

| 컴포넌트 | 역할 |
| --- | --- |
| `Screen` | Safe Area와 스크롤 처리 |
| `ResponsiveContainer` | 반응형 좌우 여백과 최대 폭 |
| `Stack` | 세로·가로 Flex 배치 |
| `AppButton` | 버튼 크기, 색상, 로딩, 비활성 상태 |
| `ThemedText` | 테마가 적용된 텍스트 |
| `ThemedView` | 테마가 적용된 View |

### 어디까지 공통으로 만들어야 하나요?

여러 기능에서 사용할 수 있는 UI만 `components/ui`에 둡니다.

```text
여러 기능에서 사용하는 버튼
→ components/ui/app-button.tsx

로그인에서만 사용하는 폼
→ features/auth/components/login-form.tsx

로그인 화면 전체
→ features/auth/screens/login-screen.tsx
```

공통 UI 안에는 로그인 API 호출처럼 특정 기능의 로직을 넣지 않습니다.

---

## 6. ESLint란?

ESLint는 코드를 실행하기 전에 문제 가능성이 있는 코드를 찾아주는 검사 도구입니다.

쉽게 말하면 코드의 맞춤법 검사기와 비슷합니다.

### TypeScript와 무엇이 다른가요?

```text
TypeScript
→ 타입이 올바른지 검사

ESLint
→ 코드 사용 방식이 안전하고 규칙에 맞는지 검사

Test
→ 실제 기능이 예상대로 동작하는지 검사
```

예를 들어 아래 코드는 타입은 올바를 수 있지만 React 동작에는 문제가 생길 수 있습니다.

```tsx
useEffect(() => {
  loadUser(userId);
}, []);
```

`userId`가 바뀌어도 Effect가 다시 실행되지 않습니다.

ESLint는 이런 Hook 의존성 문제를 찾아줄 수 있습니다.

### ESLint가 검사하는 대표 항목

- 사용하지 않는 import와 변수
- 잘못된 React Hook 호출
- `useEffect` 의존성 누락
- Effect 안의 불필요한 동기 `setState`
- 도달할 수 없는 코드
- 위험하거나 불필요한 코드 패턴
- 프로젝트에서 정한 코드 규칙

### ESLint는 언제 실행하나요?

다음 시점에는 반드시 실행합니다.

1. 기능 구현이 끝났을 때
2. 커밋 또는 Pull Request를 올리기 전
3. 다른 브랜치를 merge한 후
4. 공통 Hook이나 공통 컴포넌트를 수정한 후

코딩 중에는 VS Code ESLint 확장을 사용하면 문제를 바로 확인할 수 있습니다.

### ESLint 실행

명령어는 `baro-app` 폴더에서 실행합니다.

```powershell
cd frontend\baro-app
npm.cmd run lint
```

자동 수정 가능한 문제까지 고치려면 다음 명령을 사용합니다.

```powershell
npm.cmd run lint -- --fix
```

특정 파일만 검사할 수도 있습니다.

```powershell
npx.cmd eslint src/hooks/use-color-scheme.web.ts
```

### 오류 메시지 읽는 방법

```text
src/hooks/use-color-scheme.web.ts
  11:5  error  Calling setState synchronously within an effect
```

각 부분의 의미는 다음과 같습니다.

```text
src/hooks/use-color-scheme.web.ts  → 문제가 발생한 파일
11:5                               → 11번째 줄, 5번째 칸
error                              → 반드시 수정해야 하는 문제
Calling setState...                → 문제 설명
```

VS Code에서는 터미널의 파일 경로를 `Ctrl + 클릭`하거나 `Ctrl + Shift + M`으로 Problems 패널을 열 수 있습니다.

### `error`와 `warning`

- `error`: 린트 실패. 커밋 전에 수정해야 함
- `warning`: 실행은 가능하지만 검토가 필요한 코드

### `--fix`가 모든 문제를 고치나요?

아닙니다.

들여쓰기나 일부 import 문제는 자동 수정할 수 있지만, Hook 사용이나 비즈니스 로직은 개발자가 판단해야 합니다.

`--fix` 실행 후에도 반드시 다시 검사합니다.

```powershell
npm.cmd run lint
```

### 규칙을 끄면 안 되나요?

오류가 난다는 이유만으로 규칙을 프로젝트 전체에서 끄지 않습니다.

먼저 코드를 수정할 방법을 찾습니다.

정말 예외가 필요한 경우에만 이유를 적고 최소 범위에서 비활성화합니다.

```ts
// 해당 외부 API는 초기 마운트 시 한 번만 호출해야 한다.
// eslint-disable-next-line react-hooks/exhaustive-deps
```

AI가 제안했다는 이유만으로 ESLint 비활성화 주석을 추가하지 않습니다.

---

## 7. TypeScript 검사

TypeScript 검사는 다음 명령으로 실행합니다.

```powershell
npm.cmd run typecheck
```

다음과 같은 문제를 찾습니다.

- 잘못된 타입 전달
- 존재하지 않는 속성 접근
- 필수 props 누락
- API 응답 타입 불일치
- 잘못된 함수 반환값

기능 작업이 끝나면 ESLint와 TypeScript를 모두 실행합니다.

```powershell
npm.cmd run typecheck
npm.cmd run lint
```

두 명령은 서로 대체할 수 없습니다.

---

## 8. 주석은 어떻게 작성하나요?

모든 줄과 함수에 주석을 작성하지 않습니다.

코드가 무엇을 하는지는 이름으로 표현하고, 주석은 **왜 이렇게 작성했는지**를 설명합니다.

```ts
// 좋지 않은 주석
// 로그인 버튼을 누르면 로그인한다.
await login();

// 좋은 주석
// 세션 복원 중에는 로그인 여부를 확정할 수 없어 화면 전환을 보류한다.
if (status === 'loading') {
  return null;
}
```

다음 경우에는 짧은 주석을 작성하는 것이 좋습니다.

- 복잡한 비즈니스 규칙
- Android, iOS, Web의 동작 차이
- 인증과 보안 처리
- 임시 우회 코드
- 코드를 읽는 것만으로 이유를 알기 어려운 처리

`TODO`에는 가능하면 이슈 번호나 제거 조건을 작성합니다.

```ts
// TODO(#123): refresh API가 완성되면 임시 갱신 로직을 교체한다.
```

---

## 9. 새로운 화면을 만드는 순서

예를 들어 비밀번호 찾기 화면을 만든다고 가정합니다.

### 1단계: 라우트 파일 만들기

```tsx
// src/app/auth/find-password.tsx
export { default } from '@/features/auth/screens/find-password-screen';
```

### 2단계: 실제 화면 만들기

```tsx
// src/features/auth/screens/find-password-screen.tsx
import { ResponsiveContainer, Screen, Stack, ThemedText } from '@/components/ui';
import { Spacing } from '@/styles';

export default function FindPasswordScreen() {
  return (
    <Screen scroll>
      <ResponsiveContainer>
        <Stack gap={Spacing.md}>
          <ThemedText type="subtitle">비밀번호 찾기</ThemedText>
        </Stack>
      </ResponsiveContainer>
    </Screen>
  );
}
```

### 3단계: 필요한 경우에만 스타일 파일 만들기

```text
find-password-screen.tsx
find-password-screen.styles.ts
```

### 4단계: 주소 확인하기

```text
http://localhost:8081/auth/find-password
```

### 5단계: 검사하기

```powershell
npm.cmd run typecheck
npm.cmd run lint
```

---

## 10. AI를 사용할 때 지켜야 할 규칙

AI에게 작업을 요청할 때는 다음 내용을 함께 전달합니다.

1. 먼저 `AGENTS.md`를 읽을 것
2. 기존 공통 컴포넌트와 스타일 토큰을 확인할 것
3. `src/app`에는 라우트만 둘 것
4. 실제 기능은 `src/features`에 작성할 것
5. Flex와 반응형 구조를 사용할 것
6. 임의의 고정 너비와 색상값을 피할 것
7. 작업 후 typecheck와 lint를 실행할 것
8. 기존 코드를 임의로 삭제하지 않을 것

### AI 요청 예시

```text
AGENTS.md와 기존 공통 UI를 먼저 확인해줘.

로그인 화면을 구현하되 다음 규칙을 지켜줘.
- src/app에는 라우트만 작성
- 실제 화면은 features/auth에 작성
- Screen, ResponsiveContainer, Stack, AppButton 재사용
- 색상과 간격은 src/styles 토큰 사용
- 작은 모바일과 웹에서 반응형으로 동작
- 로딩과 오류 상태 처리
- 작업 후 typecheck와 lint 실행
```

AI가 작성한 코드도 반드시 사람이 확인해야 합니다.

특히 다음 항목을 확인합니다.

- API 주소와 필드가 실제 백엔드 계약과 같은가?
- 보안 정보가 로그에 출력되지 않는가?
- 기존 공통 컴포넌트를 중복해서 만들지 않았는가?
- ESLint 규칙을 이유 없이 끄지 않았는가?
- 모바일과 웹에서 화면이 잘리지 않는가?

---

## 11. 기본 작업 순서

```text
1. 관련 파일과 공통 컴포넌트 확인
2. 백엔드 API 계약 확인
3. 기능 구현
4. 작은 화면과 넓은 화면 확인
5. TypeScript 검사
6. ESLint 검사
7. 불필요한 로그와 임시 코드 제거
8. 커밋 또는 Pull Request
```

명령어로 정리하면 다음과 같습니다.

```powershell
cd frontend\baro-app

npm.cmd run typecheck
npm.cmd run lint
```

---

## 12. 작업 완료 체크리스트

### 구조

- [ ] `src/app`에는 라우트와 레이아웃만 있는가?
- [ ] 실제 기능은 올바른 `features` 폴더에 있는가?
- [ ] 기존 공통 컴포넌트를 먼저 확인했는가?

### 스타일

- [ ] 색상과 간격에 공통 토큰을 사용했는가?
- [ ] 불필요한 고정 너비를 사용하지 않았는가?
- [ ] Flex와 반응형 구조를 사용했는가?
- [ ] 작은 모바일 화면에서 내용이 잘리지 않는가?
- [ ] 웹의 넓은 화면에서 콘텐츠가 지나치게 늘어나지 않는가?

### 기능

- [ ] 로딩 상태를 처리했는가?
- [ ] 오류 상태를 처리했는가?
- [ ] 버튼 중복 제출을 막았는가?
- [ ] 개인정보와 토큰을 로그에 출력하지 않았는가?

### 검증

- [ ] `npm.cmd run typecheck`가 통과하는가?
- [ ] `npm.cmd run lint`가 통과하는가?
- [ ] 디버그용 `console.log`가 남아 있지 않은가?
- [ ] 변경한 화면을 직접 실행해 확인했는가?

