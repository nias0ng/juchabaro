# 출차 구역 외부측 도달을 통과 조건으로 요구하는 설계 (Jira 571)

## 배경

Jira 565가 SessionExit 발행 조건을 "5초 부재"에서 **"마지막 관측 위치가 출차 구역(`ENTRY_EXIT` / `EXIT`)"** 으로 바꿨다. 주차 칸에 서 있는 차가 가려져 세션이 조기 종료되는 — 가장 자주 나던 — 오출차가 없어졌다.

565 이후 남은 오출차는 두 가지다.

1. **출차 구역 안에 정지한 채 가려진 차량.** 출차 통로에 불법 정차했거나 배회 중인 차가 가려지면 여전히 출차로 확정된다.
2. **추적이 끊긴 뒤 되돌아온 차량.** 5초 부재가 확정된 뒤 되돌아오면 오출차다.

2번은 재식별 없이는 해결할 수 없다. `monitoring_factory.py`가 `reidentification_max_gap_seconds < absence_confirmation_seconds`를 **강제**하므로, 부재가 확정된 차량은 정의상 같은 차로 다시 알아볼 수 없다. `GeometricEntityResolver`도 durable bbox checkpoint가 없어 `RestartAwareEntityResolver`를 의도적으로 구현하지 않는다. 따라서 "나중에 같은 차가 나타나면 철회한다"는 메커니즘은 이 구조에서 성립하지 않는다.

이 스펙은 **1번만** 다룬다. 2번은 재식별 강화가 선행되어야 하는 별개 작업이다.

## 결정: 방향이 아니라 위치로 판정한다

원래 검토한 흐름은 "출차 구역 진입 → 기준선 통과 → 일정 시간 외부 방향 유지"였다. 이 중 **방향 조건을 쓰지 않는다.**

이유는 방향 조건이 오출차를 미탐으로 바꾸기만 하기 때문이다. 차가 출차 구역에 들어와 차단기 앞에서 정지했다가 차단기가 열려 나가는 경우, 정지한 순간 추적이 끊기면 마지막 motion이 STATIONARY다. 방향을 요구하면 출차가 확정되지 않고 세션이 영구 미결로 남는다(565가 채택한 "근거 없으면 발행하지 않는다" 규칙 때문이다).

문제는 이 상황이 우리가 막으려는 오출차(출차 구역에 정지한 채 가려짐)와 **그 시점에는 구분되지 않는다는 것**이다. 하나는 그 뒤에 나갔고 하나는 안 나갔을 뿐이다. 반면 게이트 앞 정지는 실제 운영에서 흔하고, 출차 통로 불법 정차는 드물다. 방향 조건은 흔한 케이스를 미탐으로 만들고 드문 케이스를 막는 교환이다.

위치 조건은 이 교환을 하지 않는다.

| 상황 | 위치 조건 |
|---|---|
| 차단기 앞 정지 후 추적 끊김 | 이미 외부측에 도달 → 통과 인정 |
| 출차 통로 안쪽에 정차한 채 가려짐 | 외부측 미도달 → 통과 불인정 |
| 주차 조종 중 출차 구역을 스침 | 내부측만 접촉 → 통과 불인정 |

위치는 motion 이력에 의존하지 않으므로 추적이 끊겨도 마지막 관측 위치만으로 판정된다. 새 임계값도 필요 없다(§임계값 참고).

## 결정: 외부측을 폴리곤에서 유도한다

`zone_definition.json`에는 기준선이나 외부 방향 필드가 없다. 새 필드를 추가하지 않고 기존 폴리곤에서 유도한다.

**외부 방향** = (가장 가까운 `AISLE` 구역의 중심 → 대상 `EXIT` 구역의 중심) 단위벡터.

**기준선** = `EXIT` 구역 중심을 지나고 외부 방향에 수직인 직선.

**외부측 sub-polygon** = `EXIT` 폴리곤을 그 직선으로 자른 외부 방향 쪽 조각.

배포 중인 두 설정으로 실측한 값이다.

| 항목 | `zone_definition.json` | `zone_definition.pilot.json` |
|---|---|---|
| AISLE(7) 중심 | (0.497, 0.482) | (0.455, 0.482) |
| EXIT(9) 중심 | (0.665, 0.166) | (0.637, 0.166) |
| 외부 방향 단위벡터 | (+0.47, −0.88) | (+0.50, −0.87) |

차량이 실제로 화면 **오른쪽 위**로 빠져나간다는 것을 현장 확인으로 검증했고, 위 유도값이 그 방향과 일치한다. 추가 근거로 zone 9는 4개 정점 중 3개를 AISLE 폴리곤과 공유하며, 공유하지 않는 자유 경계가 위·오른쪽이다 — 두 유도 방식이 같은 답을 낸다.

`AISLE` 구역이 없으면 외부 방향을 유도할 수 없다. 이때는 해당 `EXIT` 구역의 외부측 sub-polygon을 만들지 않고, 그 구역으로는 통과를 확정하지 않는다(fail-safe). 구성 시점에 경고 로그를 남긴다.

`AISLE` 구역이 여러 개면 중심 간 거리가 가장 가까운 것을 쓴다. 결정적이어야 하므로 거리가 같으면 `zone_id`가 작은 것을 쓴다.

## 결정: 임계값을 새로 만들지 않는다

- **기준선 위치**: 폴리곤 중심을 쓴다. 튜닝 상수가 아니라 기하에서 유도되는 값이다.
- **접촉 판정**: 차량 bbox와 외부측 sub-polygon의 교차 면적이 **0보다 크면** 접촉으로 본다. 비율 임계값을 두지 않는다. 차량이 기준선을 물리적으로 넘었다는 사실만 요구하는 것이고, 이 스펙의 의미("외부측에 도달했다")와 정확히 일치한다.

`_min_overlap_ratio`를 재사용하지 않는 이유는 그 값이 "구역 안에 있다"를 판정하는 비율이고, sub-polygon은 원래 구역의 절반이라 같은 비율을 요구하면 의미가 달라지기 때문이다.

## 판정 규칙

`ParkingPipeline.exit_zone_traversal_observed(physical_vehicle_id)`의 내부를 다음으로 바꾼다.

**통과 = 열려 있는 `EXIT` role ZoneVisit이 있고, 그 차량의 가장 최근 관측 프레임에서 해당 구역의 외부측 sub-polygon과 접촉했다.**

565가 만든 이 메서드의 시그니처와 호출 지점은 바뀌지 않는다. `PhysicalPresenceWorkflow`, `ParkingSessionMirror`, `ParkingEpisode`/`Incident` 전파, Outbox는 한 줄도 바뀌지 않는다 — 565가 이 메서드를 확장 지점으로 남겨둔 이유가 이것이다.

## 외부측 접촉 상태를 어디에 두는가

`ZoneVisit`에는 좌표 필드가 없다(`visit_id`, `state`, 타이머, 시각뿐). `ZoneVisitTracker`도 `PresenceSignal` 삼상태만 받아 위치를 모른다. 그래서 접촉 사실은 `ParkingPipeline`이 직접 들고 있어야 한다.

`ParkingPipeline`에 차량별 "가장 최근 **신뢰 가능한** 관측 프레임에서 접촉한 `EXIT` 구역 id 집합"을 두고, `process()`가 그런 차량마다 매 프레임 **덮어쓴다.** 관측되지 않은 차량의 값은 건드리지 않는다(그래야 부재 5초 뒤에도 마지막 관측 시점의 값이 남는다).

"신뢰 가능한"의 기준은 기존 `_presence_signal`과 동일하게 `observation.state is ObservationState.OBSERVED`다. degraded/unknown 프레임에서는 bbox의 공간적 의미를 신뢰할 수 없으므로 덮어쓰지 않고 이전 값을 보존한다 — 이 프레임들이 ZoneVisit 타이머도 전진시키지 않는 것과 같은 이유다.

- 매 프레임 덮어쓰므로 오래된 접촉이 남아 오판을 만들 수 없다. 별도 만료 로직이 필요 없다.
- `physical_exit()`과 tracking owner의 `forget` 경로에서 해당 차량 항목을 지운다.
- 기존 `checkpoint_state()`/`restore_state()`에 이 상태를 포함시켜 frame UnitOfWork 롤백 시 함께 되돌린다. 현재 4-tuple이 5-tuple이 되고 `len(checkpoint) != 4` 검사도 함께 바뀐다.

**재시작 시 이 상태는 소실된다.** ZoneVisit은 DB에서 복원되지만 접촉 사실은 in-memory였으므로, 재시작 직후 부재가 확정된 차량은 통과가 확정되지 않는다 — 발행하지 않는다. 565의 "근거 없으면 발행하지 않는다"와 같은 방향의 fail-safe이며, 결과는 해당 세션의 행정 종료가 필요해지는 것이다. durable화는 이 스펙의 범위가 아니다(§비범위).

## 변경 사항

### 1. `geometry.py`에 공개 half-plane 클리핑 추가

`_clip_half_plane`(이미 존재, private)을 사용하는 공개 함수를 추가한다.

```python
def clip_polygon_to_half_plane(
    points: Sequence[tuple[float, float]],
    origin: tuple[float, float],
    direction: tuple[float, float],
) -> list[tuple[float, float]]:
    """``origin``을 지나 ``direction`` 쪽 반평면으로 polygon을 자른다."""
```

`direction`이 영벡터면 `ValueError`. 결과가 3점 미만이면 빈 리스트(면적 0인 조각).

### 2. `geometry.py`에 폴리곤 중심, `zone_registry.py`에 외부측 유도

`geometry.py`에 추가한다.

- `polygon_centroid(points) -> tuple[float, float]` — shoelace 가중 중심. 면적이 0이면 `ValueError`.

`ZoneRegistry`에 추가한다.

- `ZoneRegistry.exit_outward_polygons() -> dict[ZoneId, NormalizedPolygon]` — `EXIT` role 구역별 외부측 sub-polygon. 구성 시 한 번 계산해 캐시한다. `AISLE`이 없거나 조각 면적이 0이면 그 구역을 결과에서 빼고 경고 로그를 남긴다.

구역 정의는 불변이므로 이 계산은 registry 생성 시 1회다. 매 프레임 비용이 없다.

### 3. `ParkingPipeline`에 외부측 접촉 추적과 판정 배선

- `process()`의 차량 루프에서, 관측된 차량마다 외부측 sub-polygon과의 교차 면적이 양수인 `EXIT` 구역 id 집합을 계산해 저장한다.
- `exit_zone_traversal_observed()`가 열린 `EXIT` role visit의 `zone_id`가 그 집합에 있는지 확인한다.
- `physical_exit()`과 `forget` 경로에서 항목을 정리한다.
- `checkpoint_state()`/`restore_state()`에 포함한다.

## 테스트 계획

- 외부측 도달 후 미관측 → 통과 인정
- 내부측만 접촉한 뒤 미관측 → 통과 불인정 (565의 기존 동작에서 바뀌는 지점)
- 외부측에 정지(STATIONARY)한 채 미관측 → 통과 인정 (방향 조건을 쓰지 않는다는 결정을 고정)
- 외부측 접촉 후 내부측으로 되돌아가 관측됨 → 통과 불인정 (매 프레임 덮어쓰기 검증)
- `EXIT` 아닌 구역(`GENERAL`/`AISLE`/`ENTRY` role)의 외부측 접촉은 통과 근거가 아님
- `AISLE` 구역이 없는 registry → 통과가 확정되지 않고 예외도 나지 않음
- `physical_exit()` 후 통과 불인정 (565의 읽기 순서 회귀 테스트 유지)
- `checkpoint_state()`/`restore_state()` 왕복 후 접촉 상태가 보존됨
- `clip_polygon_to_half_plane` 단위 테스트: 완전 포함, 완전 배제, 부분 절단, 영벡터 거부
- 실제 배포 설정 두 개(`zone_definition.json`, `zone_definition.pilot.json`)로 외부측 방향이 (+x, −y) 사분면임을 고정

## 받아들이는 대가

- **재시작 직후 부재 확정 차량은 발행되지 않는다.** 위 §외부측 접촉 상태 참고.
- **"추적 끊긴 뒤 되돌아옴"은 여전히 오출차다.** 재식별 강화가 선행 조건이다.
- **외부측 도달 후 실제로는 나가지 않고 되돌아간 차량**은, 되돌아가는 동안 관측되면 접촉 집합이 덮어써져 안전하다. 되돌아가는 순간부터 추적이 끊기면 오출차다.

## 비범위 / 후속

- **접촉 상태의 durable화**: 재시작 fail-safe를 없애려면 영속이 필요하고 마이그레이션이 따른다. 파일럿에서 재시작 직후 미결 세션이 실제로 문제가 되는지 확인한 뒤 판단한다.
- **재식별 강화**: `reidentification_max_gap_seconds < absence_confirmation_seconds` 불변식을 뒤집는 작업. "부재 확정 후 재식별"이라는 새 상태와 child scope 되살리기 설계가 필요하다.
- **방향 판정**: 이 스펙에서 의식적으로 배제했다. `MotionEstimator._motion_metrics`가 이미 `trend_vector`를 계산하고 버리므로 필요해지면 노출은 작은 작업이지만, §결정에 적은 이유로 지금은 추가하지 않는다.
- **폴리곤 조정**: 출차 폴리곤 상단(y≈0.08)과 프레임 경계 사이 여백에서 마지막 관측이 끊기는 문제는 565의 후속으로 남아 있다. 설정 변경 사안이다.
