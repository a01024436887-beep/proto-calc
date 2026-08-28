#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""축구토토 승무패 현재 회차 수집 → data/games.json 갱신.

데이터 소스: 베트맨(betman.co.kr)이 자기 페이지에서 쓰는 내부 JSON 엔드포인트.

  POST /buyPsblGame/inqCacheBuyAbleGameInfoList.do  → 현재 판매중인 게임 목록
  POST /buyPsblGame/gameInfoInq.do  {gmId, gmTs}    → 회차 상세(14경기)
  POST /buyPsblGame/closedList.do   {gmId}          → 마감된 회차 목록(--seed-latest 전용)

축구토토 승무패의 게임 코드는 gmId=G011 / gameTypeCode=TSCWDL 이다.
둘 중 하나만 맞아도 후보로 잡아, 한쪽이 바뀌어도 버티게 한다.

세션·재시도·`_sbmInfo` 봉투·시각 포맷 등 공통부는 betman.py에 있다
(프로토 승부식 수집 fetch_proto.py와 공유).

실패해도 절대 기존 data/games.json을 덮어쓰지 않고 exit 0으로 끝낸다.
(워크플로를 실패로 만들지 않기 위함 — 페이지는 계속 살아 있어야 한다.)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

import requests

from betman import (
    BASE,
    KST,
    ROOT,
    buyable_games,
    clean,
    fmt_kst,
    log,
    make_session,
    post_json,
    write_json_if_changed,
)

GM_ID = "G011"
GAME_TYPE_CODE = "TSCWDL"
EXPECTED_GAMES = 14

OUT_PATH = ROOT / "data" / "games.json"


# ---------------------------------------------------------------- source


def is_seungmupae(entry: dict) -> bool:
    master = entry.get("gameMaster") or {}
    return entry.get("gmId") == GM_ID or master.get("gameTypeCode") == GAME_TYPE_CODE


def pick_on_sale(session: requests.Session) -> dict | None:
    """판매중인 승무패 회차 중 마감이 가장 가까운(아직 안 지난) 것."""
    data = buyable_games(session)
    now_ms = data.get("currentTime") or int(datetime.now(tz=KST).timestamp() * 1000)
    pool = (data.get("totoGames") or []) + (data.get("protoGames") or [])

    candidates = [
        e
        for e in pool
        if is_seungmupae(e)
        and isinstance(e.get("saleEndDate"), int)
        and e["saleEndDate"] > now_ms
    ]
    if not candidates:
        log("판매중인 축구토토 승무패 회차 없음 (현재 판매중 게임 %d개)" % len(pool))
        return None

    chosen = min(candidates, key=lambda e: e["saleEndDate"])
    log("판매중 회차 후보 %d개 → gmTs=%s 선택" % (len(candidates), chosen.get("gmTs")))
    return chosen


def pick_latest_closed(session: requests.Session) -> dict | None:
    """--seed-latest: 판매중이 없을 때 가장 최근 마감 회차 (최초 시드 전용)."""
    data = post_json(
        session,
        "/buyPsblGame/closedList.do",
        {"gmId": GM_ID, "draw": 1, "start": 0, "length": 1},
        referer=BASE + "/main/mainPage/gamebuy/closedGameList.do",
    )
    rows = ((data.get("schedules") or {}).get("data")) or []
    if not rows:
        log("마감 회차 목록도 비어 있음")
        return None
    log("최근 마감 회차 gmTs=%s 사용 (시드 모드)" % rows[0].get("gmTs"))
    return rows[0]


def build_payload(session: requests.Session, entry: dict) -> dict:
    """회차 상세를 받아 프런트가 기대하는 스키마로 변환."""
    detail = post_json(
        session,
        "/buyPsblGame/gameInfoInq.do",
        {"gmId": entry.get("gmId") or GM_ID, "gmTs": entry.get("gmTs"), "gameYear": ""},
        referer=BASE + "/main/mainPage/gamebuy/gameSlip.do",
    )

    lottery = detail.get("currentLottery") or {}
    round_no = lottery.get("gmOsidTs") or entry.get("gmOsidTs")
    if round_no is None:
        raise ValueError("회차 번호(gmOsidTs)를 찾을 수 없음")

    sale_end = lottery.get("saleEndDate") or entry.get("saleEndDate")

    games = []
    for idx, s in enumerate(detail.get("schedulesList") or []):
        home = clean(s.get("homeFullName") or s.get("homeName"))
        away = clean(s.get("awayFullName") or s.get("awayName"))
        if not home or not away:
            raise ValueError("%d번째 경기의 팀명이 비어 있음" % (idx + 1))

        game = {"no": int(s.get("matchSeq") or idx + 1), "home": home, "away": away}
        league = clean(s.get("leagueName"))
        if league:
            game["league"] = league
        kickoff = s.get("gameDate")
        if isinstance(kickoff, int):
            game["kickoff"] = fmt_kst(kickoff)
        games.append(game)

    games.sort(key=lambda g: g["no"])

    payload = {
        "round": str(round_no),
        "updated": datetime.now(tz=KST).isoformat(timespec="seconds"),
        "games": games,
    }
    if isinstance(sale_end, int):
        payload["deadline"] = fmt_kst(sale_end)
    return payload


# ---------------------------------------------------------------- validate


def validate(payload: dict) -> None:
    """깨진 데이터가 커밋되지 않게 막는 마지막 관문."""
    games = payload.get("games") or []
    if len(games) != EXPECTED_GAMES:
        raise ValueError("경기 수가 %d개 (14개여야 함)" % len(games))

    numbers = sorted(g["no"] for g in games)
    if numbers != list(range(1, EXPECTED_GAMES + 1)):
        raise ValueError("경기 번호가 1~14가 아님: %s" % numbers)

    for g in games:
        if not g.get("home") or not g.get("away"):
            raise ValueError("%s번 경기 팀명이 비어 있음" % g["no"])

    if not payload.get("round"):
        raise ValueError("회차 번호가 비어 있음")


# ---------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description="축구토토 승무패 회차 수집")
    parser.add_argument(
        "--seed-latest",
        action="store_true",
        help="판매중인 회차가 없으면 가장 최근 마감 회차로 채운다 "
        "(최초 시드용. 스케줄 실행에는 쓰지 않는다)",
    )
    args = parser.parse_args()

    try:
        session = make_session()
        entry = pick_on_sale(session)
        if entry is None and args.seed_latest:
            entry = pick_latest_closed(session)
        if entry is None:
            log("→ 기존 data/games.json 유지, 종료")
            return 0

        payload = build_payload(session, entry)
        log(
            "수집: 제%s회차 / %d경기 / 마감 %s"
            % (payload["round"], len(payload["games"]), payload.get("deadline", "?"))
        )
        validate(payload)
        write_json_if_changed(OUT_PATH, payload, "data/games.json")
        return 0

    except Exception as exc:
        # 네트워크 오류·사이트 구조 변경 등: 로그만 남기고 기존 파일을 지킨다.
        log("[실패] %s: %s" % (type(exc).__name__, exc))
        log("→ 기존 data/games.json 유지, 종료 (워크플로는 성공 처리)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
