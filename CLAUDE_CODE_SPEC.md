# 승무패 조합 계산기 — 배포 + 회차 자동 갱신 스펙

이 문서를 읽고 그대로 구현해 주세요. 프런트엔드(index.html)는 이미 완성되어 있으므로
**수정하지 말고**, 배포와 데이터 자동 갱신 파이프라인만 만들면 됩니다.

## 1. 목표

1. 같은 폴더의 `index.html`(승무패 14경기 조합 계산기)을 **GitHub Pages**로 배포해서
   휴대폰·다른 데스크탑 어디서든 URL 하나로 접속할 수 있게 한다.
2. **GitHub Actions**가 하루 2회 자동 실행되어, 현재 판매 중인 축구토토 승무패 회차의
   14경기 정보(홈팀/원정팀/경기 일시/리그)를 가져와 `data/games.json`을 갱신한다.
   (승무패는 대략 주 2회 새 회차가 나오므로, 하루 2회 확인하면 항상 최신 회차가 잡힌다.)
3. 프런트는 이미 `data/games.json`을 읽어서 회차 번호·마감 시각·경기별 팀명을
   표시하도록 구현되어 있다. 파일이 없거나 형식이 틀리면 조용히 번호만 표시한다.

## 2. 리포 구조

```
/                          # 리포 루트 = Pages 루트
├─ index.html              # 첨부된 파일 그대로 (수정 금지)
├─ data/
│  └─ games.json           # 자동 갱신 대상
├─ scripts/
│  └─ fetch_games.py       # 회차 수집 스크립트 (Python 3.11+)
├─ requirements.txt        # requests 등 최소 의존성
├─ .github/workflows/
│  └─ update.yml           # 스케줄 실행 + 커밋
└─ README.md               # 접속 주소, 운영 방법, 수동 갱신법
```

## 3. data/games.json 스키마 (프런트가 기대하는 형식 — 반드시 준수)

```json
{
  "round": "123",
  "deadline": "11/23(토) 19:30",
  "updated": "2026-08-27T09:00:00+09:00",
  "games": [
    { "no": 1, "league": "EPL", "home": "맨시티", "away": "첼시", "kickoff": "11/23(토) 21:00" }
  ]
}
```

- `games`는 정확히 14개, `no`는 1~14.
- `kickoff`와 `deadline`은 **KST 기준으로 미리 포맷한 표시용 문자열**로 넣는다
  (예: `11/23(토) 21:00`). 프런트에서 날짜 계산을 하지 않는다.
- `league`, `kickoff`는 없으면 생략 가능. `home`/`away`는 필수.

## 4. 데이터 소스 조사 (첫 작업)

정해진 API가 없으므로 먼저 소스를 조사한다.

1. 1순위: 베트맨(betman.co.kr, 스포츠토토 공식 온라인 발매 사이트)의 축구토토 승무패
   게임 페이지. 브라우저 개발자도구로 확인하듯 페이지가 사용하는 내부 XHR/JSON
   엔드포인트를 찾아 requests로 재현한다. (세션/Referer/User-Agent 헤더가 필요할 수 있음)
2. 대안: wisetoto.com 등 회차별 승무패 대상 경기를 정리해 주는 사이트.
3. 회차 선택 로직: "판매중" 상태인 회차를 고른다. 판매중인 회차가 둘 이상이면
   마감이 가장 가까운(아직 지나지 않은) 회차를 고른다. 판매중이 없으면 기존 파일 유지.

주의: 개인용 도구이므로 요청은 하루 2회 수준으로만 보내고, User-Agent를 명시하며,
robots.txt를 존중한다. 사이트 구조가 바뀌어 파싱이 깨질 수 있으니 아래 안전장치를 지킨다.

## 5. scripts/fetch_games.py 요구사항

- Python 3.11+, 의존성은 requests(필요시 beautifulsoup4)로 최소화.
- 실행 결과를 표준 출력에 명확히 로그(회차 번호, 경기 수, 변경 여부).
- **검증**: 경기 수가 14개가 아니거나 팀명이 비면 실패로 처리하고, 기존
  `data/games.json`을 절대 덮어쓰지 않는다 (exit code 0으로 종료해 워크플로는 성공 처리).
- 내용이 기존 파일과 동일하면 파일을 다시 쓰지 않는다 (불필요한 커밋 방지).
- 시간 포맷은 `Asia/Seoul` 기준, 요일은 한글(월~일).
- 네트워크 오류·구조 변경 시 예외를 삼키고 로그만 남긴다. 페이지가 죽으면 안 된다.

## 6. .github/workflows/update.yml 요구사항

- 트리거: `schedule`(cron `0 22 * * *`, `0 10 * * *` → KST 07:00 / 19:00 하루 2회)
  + `workflow_dispatch`(수동 실행).
- 단계: checkout → setup-python → `pip install -r requirements.txt` →
  `python scripts/fetch_games.py` → `data/games.json` 변경 시에만
  `git commit -m "data: 제N회차 갱신"` 후 push.
- `permissions: contents: write` 필요.

## 7. 배포

- GitHub Pages: main 브랜치 루트에서 서빙(Deploy from a branch). gh CLI가 있으면
  리포 생성부터 Pages 활성화까지 진행하고, 안 되면 사용자가 웹에서 켤 수 있게
  Settings → Pages 경로를 README에 적는다.
- 완료 기준:
  1) `https://<계정>.github.io/<리포>/` 접속 시 계산기가 뜨고, games.json이 있으면
     상단에 "제N회 · 마감 …"과 경기별 팀명이 보인다.
  2) Actions 탭에서 workflow_dispatch로 수동 갱신이 성공한다.
  3) README에 접속 주소, 자동 갱신 시각, 수동 갱신 방법, 소스가 깨졌을 때
     games.json을 손으로 고치는 방법(스키마 예시 포함)이 정리되어 있다.

## 8. 하지 말 것

- index.html 수정 (버그가 아닌 이상). 발견한 버그는 고치기 전에 보고.
- 14개 미만/파싱 실패 데이터 커밋.
- 과도한 크롤링(스케줄 외 반복 요청, 병렬 요청).
