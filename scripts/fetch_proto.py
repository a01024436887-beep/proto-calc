#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""프로토 승부식 축구 경기 배당 수집 → data/proto.json 갱신.

프로토 승부식은 gmId=G101 / gameTypeCode=PPTPVE (inqScheduleSltList.do로 확인).

승무패(G011)와 달리 경기 목록이 `schedulesList`가 아니라 `compSchedules`에 들어 있고,
{"keys": [컬럼명...], "datas": [[값...], ...]} 형태의 열 지향 테이블이다.

담는 것: 축구(itemCode=SC) × 일반 승무패 유형(betTypNm='승무패')만.
빼는 것: 핸디캡('일반 정수/소수핸디캡'), 언더오버, SUM(홀짝), 전반 승무패,
        축구 외 종목, 마감 지난 경기, 발매 차단 경기.
같은 경기의 일반/핸디캡/언더오버는 규정상 교차 조합이 안 되므로 섞으면 계산이 틀려진다.

경기번호(`no`)는 베트맨 화면에 그대로 표시되는 `matchSeq`를 쓴다.
(gameSlipProtoVictory.html.js가 '<span class="db">' + v.matchSeq + '</span>'로 렌더한다.
 승무패 G011에서도 matchSeq가 1~14로 화면 번호와 일치했다.)

실패해도 절대 기존 data/proto.json을 덮어쓰지 않고 exit 0으로 끝낸다.
"""

from __future__ import annotations

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
    fmt_kst_short,
    log,
    make_session,
    post_json,
    write_json_if_changed,
)

GM_ID = "G101"
GAME_TYPE_CODE = "PPTPVE"

SOCCER = "SC"
BET_TYPE_GENERAL = "승무패"  # 일반 승무패. 핸디캡/언더오버/홀짝은 다른 값이 붙는다.

OUT_PATH = ROOT / "data" / "proto.json"


# ---------------------------------------------------------------- source


def is_proto_victory(entry: dict) -> bool:
    master = entry.get("gameMaster") or {}
    return entry.get("gmId") == GM_ID or master.get("gameTypeCode") == GAME_TYPE_CODE


def pick_on_sale(session: requests.Session) -> dict | None:
    """판매중인 승부식 회차 중 마감이 가장 가까운(아직 안 지난) 것."""
    data = buyable_games(session)
    now_ms = data.get("currentTime") or int(datetime.now(tz=KST).timestamp() * 1000)
    pool = (data.get("protoGames") or []) + (data.get("totoGames") or [])

    candidates = [
        e
        for e in pool
        if is_proto_victory(e)
        and isinstance(e.get("saleEndDate"), int)
        and e["saleEndDate"] > now_ms
    ]
    if not candidates:
        log("판매중인 프로토 승부식 회차 없음 (현재 판매중 게임 %d개)" % len(pool))
        return None

    chosen = min(candidates, key=lambda e: e["saleEndDate"])
    log("판매중 회차 후보 %d개 → gmTs=%s 선택" % (len(candidates), chosen.get("gmTs")))
    return chosen


def schedule_rows(detail: dict) -> list[dict]:
    """compSchedules(열 지향)를 dict 리스트로 편다. 구형 schedulesList도 받아 준다."""
    comp = detail.get("compSchedules") or {}
    keys = comp.get("keys")
    datas = comp.get("datas")
    if isinstance(keys, list) and isinstance(datas, list):
        return [dict(zip(keys, row)) for row in datas]

    rows = detail.get("schedulesList")
    if isinstance(rows, list) and rows:
        log("compSchedules가 비어 schedulesList로 대체")
        return rows

    raise ValueError("경기 목록(compSchedules/schedulesList)을 찾을 수 없음")


def is_target(row: dict) -> bool:
    """축구 + 일반 승무패 유형만. 전반전·핸디캡·언더오버·홀짝은 제외."""
    if row.get("itemCode") != SOCCER:
        return False
    if clean(row.get("betTypNm")) != BET_TYPE_GENERAL:
        return False
    if "전반" in clean(row.get("betNm")):
        return False
    return True


def is_open(row: dict, now_ms: int) -> bool:
    """아직 발매중이고 마감이 안 지난 경기인지."""
    if clean(row.get("gameReject")) not in ("", "0"):
        return False
    if clean(row.get("buyReject")) not in ("", "0"):
        return False
    # 마감 미정 + 승배당 1.0 = 취소된 경기 (betman 프런트와 같은 판정)
    if clean(row.get("unsetEndDate")) == "Y" and row.get("winAllot") == 1:
        return False
    end = row.get("endDate")
    if isinstance(end, int) and end <= now_ms:
        return False
    return True


def odds_of(row: dict) -> dict:
    """배당은 원본 소수점 그대로. 0이거나 없으면 키를 넣지 않는다."""
    out = {}
    for key, field in (("승", "winAllot"), ("무", "drawAllot"), ("패", "loseAllot")):
        value = row.get(field)
        if isinstance(value, (int, float)) and value > 0:
            out[key] = float(value)
    return out


def build_payload(session: requests.Session, entry: dict) -> dict:
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

    rows = schedule_rows(detail)
    now = datetime.now(tz=KST)
    now_ms = int(now.timestamp() * 1000)

    targets = [r for r in rows if is_target(r)]
    open_rows = [r for r in targets if is_open(r, now_ms)]

    games = []
    no_odds = 0
    for row in open_rows:
        odds = odds_of(row)
        if not odds:
            # 배당 미정(protoStatus=1) 경기. 담아 봐야 고를 수 없으므로 뺀다.
            no_odds += 1
            continue

        home = clean(row.get("homeName"))
        away = clean(row.get("awayName"))
        if not home or not away:
            continue

        game = {"no": int(row["matchSeq"]), "home": home, "away": away, "odds": odds}
        league = clean(row.get("leagueName"))
        if league:
            game["league"] = league
        kickoff = row.get("gameDate")
        if isinstance(kickoff, int):
            game["kickoff"] = fmt_kst(kickoff)
        # 정렬용 원본 시각. 아래에서 다시 뺀다.
        games.append((kickoff if isinstance(kickoff, int) else 0, game))

    # kickoff 빠른 순 → 같은 시각이면 경기번호 순.
    games.sort(key=lambda pair: (pair[0], pair[1]["no"]))
    games = [game for _, game in games]

    log(
        "축구 일반 승무패 %d경기 중 발매중 %d경기 → 배당 있는 %d경기 담음 (배당 미정 %d경기 제외)"
        % (len(targets), len(open_rows), len(games), no_odds)
    )

    payload = {
        "round": str(round_no),
        "updated": now.isoformat(timespec="seconds"),
        "updated_label": fmt_kst_short(now_ms),
        "games": games,
    }
    if isinstance(sale_end, int):
        payload["deadline"] = fmt_kst(sale_end)
    return payload


# ---------------------------------------------------------------- validate


def validate(payload: dict) -> None:
    games = payload.get("games") or []
    if not games:
        raise ValueError("담긴 경기가 0개")

    with_odds = [g for g in games if g.get("odds")]
    if not with_odds:
        raise ValueError("배당이 있는 경기가 하나도 없음")

    numbers = [g["no"] for g in games]
    if len(set(numbers)) != len(numbers):
        raise ValueError("경기번호가 중복됨")

    if not payload.get("round"):
        raise ValueError("회차 번호가 비어 있음")


# ---------------------------------------------------------------- main


def main() -> int:
    try:
        session = make_session()
        entry = pick_on_sale(session)
        if entry is None:
            log("→ 기존 data/proto.json 유지, 종료")
            return 0

        payload = build_payload(session, entry)
        log(
            "수집: 제%s회차 / %d경기 / 마감 %s"
            % (payload["round"], len(payload["games"]), payload.get("deadline", "?"))
        )
        validate(payload)
        write_json_if_changed(OUT_PATH, payload, "data/proto.json")
        return 0

    except Exception as exc:
        log("[실패] %s: %s" % (type(exc).__name__, exc))
        log("→ 기존 data/proto.json 유지, 종료 (워크플로는 성공 처리)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
