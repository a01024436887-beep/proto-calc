#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""프로토 승부식 축구 배당 수집 → data/proto.json 갱신.

프로토 승부식은 gmId=G101. 경기 목록은 gameInfoInq.do의 `compSchedules`에
{"keys": [컬럼명...], "datas": [[값...], ...]} 열 지향 테이블로 들어 있다.

담는 것: 축구(itemCode=SC)의 **일반 승무패**, **핸디캡**(정수/소수), **언더오버**.
빼는 것: SUM(홀짝), 전반전, 축구 외 종목, 마감 지난 경기, 발매 차단 경기,
        배당 미정(protoStatus=1 → 배당이 전부 0.0).

베트맨은 같은 실제 경기의 일반·핸디캡·언더오버에 **각각 다른 경기번호**를 준다.
규정상 서로 교차 조합할 수 없으므로 각각 별도 원소로 담고 `match_key`를 같은 값으로
넣어 묶는다(프런트가 이 키로 그룹을 만들어 하나를 고르면 나머지를 잠근다).
한 경기에 핸디캡이 여러 기준값, 언더오버가 여러 구간으로 붙는 경우도 있다.

핸디캡 기준값·언더오버 구간값은 둘 다 `winHandi`(홈 기준)에 실려 온다.
`handi`는 값이 아니라 유형 코드다(승무패 0, 정수핸디캡 2, 소수핸디캡 23, 언더오버 9).

★ 언더오버 배당 매핑 — 실제 응답으로 두 번 확인함 (뒤집히면 계산이 통째로 틀어짐):
  1) 응답이 직접 라벨을 준다. 113행 전부 winTxt='언더', loseTxt='오버', drawTxt='-'.
     → "언더" = winAllot, "오버" = loseAllot, drawAllot은 0.0이라 자동으로 빠짐.
  2) 확률적으로도 맞는다. 기준선 2.5→4.5로 오르면 언더는 맞기 쉬워져 배당이 내려가고
     (1.821→1.640) 오버는 어려워져 올라간다(1.767→1.950). 뒤집혔다면 방향이 반대다.
     오버라운드(1/언더+1/오버) 평균 1.133으로 북 마진도 정상 범위.

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

# betTypNm 기준 분류. SUM('일반 홀짝')은 여기에 없어 자동 제외된다.
TYPE_GENERAL = "일반"
TYPE_HANDICAP = "핸디캡"
TYPE_OVERUNDER = "언더오버"
BET_TYPE_TO_KIND = {
    "승무패": TYPE_GENERAL,
    "일반 정수핸디캡": TYPE_HANDICAP,
    "일반 소수핸디캡": TYPE_HANDICAP,
    "일반 언더오버": TYPE_OVERUNDER,
}
TYPE_ORDER = {TYPE_GENERAL: 0, TYPE_HANDICAP: 1, TYPE_OVERUNDER: 2}

# 유형별 odds 키 ↔ 응답 컬럼. 언더오버는 winTxt/loseTxt 라벨로 확인한 매핑이다.
ODDS_FIELDS = {
    TYPE_GENERAL: (("승", "winAllot"), ("무", "drawAllot"), ("패", "loseAllot")),
    TYPE_HANDICAP: (("승", "winAllot"), ("무", "drawAllot"), ("패", "loseAllot")),
    TYPE_OVERUNDER: (("언더", "winAllot"), ("오버", "loseAllot")),
}

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


def kind_of(row: dict) -> str | None:
    """축구 일반/핸디캡이면 유형 문자열, 아니면 None."""
    if row.get("itemCode") != SOCCER:
        return None
    if "전반" in clean(row.get("betNm")):
        return None
    return BET_TYPE_TO_KIND.get(clean(row.get("betTypNm")))


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


def odds_of(row: dict, kind: str) -> dict:
    """배당은 원본 소수점 그대로. 0이거나 없으면 키를 넣지 않는다.

    소수핸디캡(.5)과 언더오버는 무승부가 없어 drawAllot이 0.0 → "무"가 자동으로 빠진다.
    """
    out = {}
    for key, field in ODDS_FIELDS[kind]:
        value = row.get(field)
        if isinstance(value, (int, float)) and value > 0:
            out[key] = float(value)
    return out


def match_key_of(row: dict) -> str:
    """같은 실제 경기를 묶는 키. 홈/원정 팀 ID + 경기 날짜(KST).

    같은 경기의 일반·핸디캡 행은 homeId/awayId/gameDate가 모두 같다(확인됨).
    킥오프 시각이 조정돼도 같은 경기의 행들은 함께 움직이므로 그룹이 깨지지 않는다.
    """
    game_date = row.get("gameDate")
    day = (
        datetime.fromtimestamp(game_date / 1000, tz=KST).strftime("%Y%m%d")
        if isinstance(game_date, int)
        else "00000000"
    )
    return "M%s-%s-%s" % (day, clean(row.get("homeId")), clean(row.get("awayId")))


def line_value(row: dict) -> float | None:
    """핸디캡 기준값 / 언더오버 구간값. 둘 다 winHandi(홈 기준)에 실려 온다."""
    value = row.get("winHandi")
    return float(value) if isinstance(value, (int, float)) else None


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

    targets = [(r, k) for r in rows for k in [kind_of(r)] if k]
    open_rows = [(r, k) for r, k in targets if is_open(r, now_ms)]

    sortable = []
    no_odds = 0
    for row, kind in open_rows:
        odds = odds_of(row, kind)
        if not odds:
            # 배당 미정(protoStatus=1). 담아 봐야 고를 수 없으므로 뺀다.
            no_odds += 1
            continue

        home = clean(row.get("homeName"))
        away = clean(row.get("awayName"))
        if not home or not away:
            continue

        key = match_key_of(row)
        game = {
            "no": int(row["matchSeq"]),
            "match_key": key,
            "type": kind,
            "home": home,
            "away": away,
            "odds": odds,
        }
        # 일반은 handicap: null, 핸디캡은 값, 언더오버는 line에 구간값.
        if kind == TYPE_OVERUNDER:
            game["line"] = line_value(row)
        else:
            game["handicap"] = line_value(row) if kind == TYPE_HANDICAP else None
        league = clean(row.get("leagueShortName")) or clean(row.get("leagueName"))
        if league:
            game["league"] = league
        kickoff = row.get("gameDate")
        if isinstance(kickoff, int):
            game["kickoff"] = fmt_kst(kickoff)

        # kickoff 빠른 순 → 같은 경기끼리 붙여서 → 일반 먼저 → 경기번호 순
        sortable.append(
            ((kickoff if isinstance(kickoff, int) else 0), key, TYPE_ORDER[kind], game["no"], game)
        )

    sortable.sort(key=lambda t: t[:4])
    games = [t[4] for t in sortable]

    match_count = len({g["match_key"] for g in games})
    kinds = {}
    for g in games:
        kinds[g["type"]] = kinds.get(g["type"], 0) + 1
    log(
        "축구 3유형 %d항목 중 발매중 %d항목 → 배당 있는 %d항목 담음 "
        "(일반 %d, 핸디캡 %d, 언더오버 %d / 실제 %d경기, 배당 미정 %d항목 제외)"
        % (
            len(targets),
            len(open_rows),
            len(games),
            kinds.get(TYPE_GENERAL, 0),
            kinds.get(TYPE_HANDICAP, 0),
            kinds.get(TYPE_OVERUNDER, 0),
            match_count,
            no_odds,
        )
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

    if not any(g.get("odds") for g in games):
        raise ValueError("배당이 있는 경기가 하나도 없음")

    numbers = [g["no"] for g in games]
    if len(set(numbers)) != len(numbers):
        raise ValueError("경기번호가 중복됨")

    for g in games:
        no, kind, keys = g["no"], g["type"], set(g["odds"])
        if kind not in TYPE_ORDER:
            raise ValueError("%s번 항목의 type이 이상함: %r" % (no, kind))
        if not g.get("match_key"):
            raise ValueError("%s번 항목에 match_key가 없음" % no)

        if kind == TYPE_OVERUNDER:
            if g.get("line") is None:
                raise ValueError("%s번 언더오버 항목에 line이 없음" % no)
            if not keys <= {"언더", "오버"}:
                raise ValueError("%s번 언더오버 항목의 odds 키가 이상함: %s" % (no, sorted(keys)))
        else:
            if not keys <= {"승", "무", "패"}:
                raise ValueError("%s번 %s 항목의 odds 키가 이상함: %s" % (no, kind, sorted(keys)))
            if kind == TYPE_GENERAL and g["handicap"] is not None:
                raise ValueError("%s번 일반 항목에 핸디캡 값이 붙어 있음" % no)
            if kind == TYPE_HANDICAP and g["handicap"] is None:
                raise ValueError("%s번 핸디캡 항목에 기준값이 없음" % no)

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
            "수집: 제%s회차 / %d항목 / 마감 %s"
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
