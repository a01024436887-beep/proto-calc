# 승무패 조합 계산기

축구토토 승무패 14경기의 **경우의 수와 총 베팅액**을 계산해 주는 한 페이지짜리 도구입니다.
아는 경기는 승·무·패 중 하나를 고르고, 모르는 경기는 "모름"을 체크하면
그 경기의 세 가지 결과가 전부 조합에 들어갑니다.

## 접속 주소

**https://a01024436887-beep.github.io/proto-calc/**

설치할 것 없이 휴대폰·데스크탑 브라우저에서 바로 열립니다. 홈 화면에 추가해 두면 편합니다.

## 화면 상단에 뜨는 회차 정보

`data/games.json`이 있으면 상단에 `축구토토 승무패 · 제47회 · 마감 8/26(수) 23:00`처럼
회차·마감 시각이 뜨고, 각 경기 줄에 리그·팀명·킥오프가 함께 표시됩니다.
파일이 없거나 형식이 깨져 있으면 조용히 경기 번호만 표시하고, 계산 기능은 그대로 동작합니다.

## 자동 갱신

GitHub Actions가 **하루 두 번, KST 07:00과 19:00**에 실행되어
현재 판매중인 승무패 회차의 14경기를 베트맨(betman.co.kr)에서 가져와
`data/games.json`을 갱신하고, 내용이 바뀐 경우에만 커밋합니다.

승무패는 대략 주 2회 새 회차가 나오므로 하루 2회 확인이면 항상 최신 회차가 잡힙니다.

- 워크플로: [`.github/workflows/update.yml`](.github/workflows/update.yml)
- 수집 스크립트: [`scripts/fetch_games.py`](scripts/fetch_games.py)

### 수동 갱신

새 회차가 떴는데 바로 반영하고 싶을 때:

1. 리포의 **Actions** 탭 → 왼쪽에서 **회차 자동 갱신** 선택
2. 오른쪽 **Run workflow** 버튼 → **Run workflow**
3. 1~2분 뒤 완료. 페이지를 새로고침하면 반영됩니다.

같은 화면의 **판매중인 회차가 없으면 최근 마감 회차로 채우기** 체크박스를 켜면
아래 `--seed-latest`와 같게 동작합니다. 평소에는 꺼 두세요.

로컬에서 돌리려면:

```bash
pip install -r requirements.txt
python scripts/fetch_games.py
```

### 판매중인 회차가 없을 때

축구 비시즌 등으로 판매중인 승무패 회차가 없으면 스크립트는
**기존 `data/games.json`을 그대로 두고** 아무것도 커밋하지 않습니다.
따라서 화면에는 직전 회차 정보가 남아 있을 수 있습니다.

가장 최근 **마감된** 회차로 강제로 채우고 싶으면(최초 시드용):

```bash
python scripts/fetch_games.py --seed-latest
```

## 소스가 깨졌을 때 — games.json 직접 고치기

베트맨 사이트 구조가 바뀌면 수집이 실패할 수 있습니다. 그래도 페이지는 죽지 않고,
스크립트는 로그만 남긴 뒤 기존 파일을 유지합니다(워크플로는 성공으로 끝납니다).
Actions 로그에 `[실패]`로 시작하는 줄이 보이면 그때가 손으로 고칠 때입니다.

`data/games.json`을 GitHub 웹 에디터에서 직접 수정하면 됩니다.
(리포 → `data/games.json` → 연필 아이콘 → 수정 → Commit)

```json
{
  "round": "48",
  "deadline": "11/23(토) 19:30",
  "updated": "2026-08-27T09:00:00+09:00",
  "games": [
    { "no": 1,  "league": "EPL", "home": "맨시티",   "away": "첼시",     "kickoff": "11/23(토) 21:00" },
    { "no": 2,  "league": "EPL", "home": "아스널",   "away": "리버풀",   "kickoff": "11/23(토) 23:00" },
    { "no": 3,  "home": "팀A", "away": "팀B" },
    { "no": 4,  "home": "팀A", "away": "팀B" },
    { "no": 5,  "home": "팀A", "away": "팀B" },
    { "no": 6,  "home": "팀A", "away": "팀B" },
    { "no": 7,  "home": "팀A", "away": "팀B" },
    { "no": 8,  "home": "팀A", "away": "팀B" },
    { "no": 9,  "home": "팀A", "away": "팀B" },
    { "no": 10, "home": "팀A", "away": "팀B" },
    { "no": 11, "home": "팀A", "away": "팀B" },
    { "no": 12, "home": "팀A", "away": "팀B" },
    { "no": 13, "home": "팀A", "away": "팀B" },
    { "no": 14, "home": "팀A", "away": "팀B" }
  ]
}
```

규칙:

| 필드 | 필수 | 설명 |
| --- | --- | --- |
| `round` | 권장 | 회차 번호. 문자열. 화면에 `제47회`로 표시 |
| `deadline` | 권장 | 구매 마감. **KST 기준으로 미리 포맷한 문자열** |
| `updated` | 선택 | 갱신 시각. 표시에는 쓰이지 않음 |
| `games` | 필수 | **정확히 14개**, `no`는 1~14 |
| `games[].home` / `.away` | 필수 | 팀명 |
| `games[].league` | 선택 | 없으면 생략 |
| `games[].kickoff` | 선택 | 없으면 생략. `deadline`과 같은 포맷 |

`kickoff`와 `deadline`은 프런트에서 날짜 계산을 하지 않으므로
`11/23(토) 21:00` 형태로 **완성된 문자열**을 넣어야 합니다. 요일은 한글(월~일)입니다.

## 리포 구조

```
/
├─ index.html              # 계산기 본체 (Pages 루트에서 서빙)
├─ proto_calc.html         # 원본 파일 (index.html과 동일)
├─ data/
│  └─ games.json           # 자동 갱신 대상
├─ scripts/
│  └─ fetch_games.py       # 회차 수집 (Python 3.11+)
├─ requirements.txt
└─ .github/workflows/
   └─ update.yml
```

## Pages 설정 (이미 켜져 있지 않다면)

리포 → **Settings** → 왼쪽 **Pages** →
**Source**: `Deploy from a branch` → **Branch**: `main` / `/ (root)` → **Save**.
1~2분 뒤 위 접속 주소가 열립니다.

## 데이터 출처와 예의

베트맨(betman.co.kr)이 자기 페이지에서 쓰는 내부 JSON 엔드포인트를 그대로 호출합니다.
개인용 도구이므로 **하루 2회**만, 순차적으로(병렬 요청 없이) 요청하며
User-Agent에 용도를 밝혀 둡니다. 스케줄 외 반복 호출은 하지 마세요.

베트맨은 첫 TLS 핸드셰이크를 간헐적으로 끊습니다(연결 리셋). 차단이 아니라 산발적인
현상이라 스크립트가 **최대 4회까지 2초씩 늘려 가며 재시도**합니다.
Actions 로그에 `연결 실패 (1/4) ... 재시도` 줄이 보이는 건 정상이며,
그 뒤 `수집: 제N회차` 가 이어지면 성공한 것입니다.

베팅 관련 정보는 참고용이며, 실제 구매 전에는 베트맨에서 회차와 경기를 다시 확인하세요.
