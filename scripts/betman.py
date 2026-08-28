#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""베트맨(betman.co.kr) 내부 JSON 엔드포인트 호출 공통부.

fetch_games.py(축구토토 승무패)와 fetch_proto.py(프로토 승부식)가 함께 쓴다.
세션 준비, `_sbmInfo` 봉투, 연결 리셋 재시도, KST 시각 포맷이 여기에 모여 있다.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

BASE = "https://www.betman.co.kr"
KST = ZoneInfo("Asia/Seoul")
WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]

ROOT = Path(__file__).resolve().parent.parent

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 "
    "(proto-calc personal tool; 2 runs per day)"
)
TIMEOUT = 25

# betman은 첫 TLS 핸드셰이크를 그냥 끊어 버리는 일이 잦다(연결 리셋).
# 차단이 아니라 간헐적 리셋이라 몇 초 뒤 재시도하면 대개 붙는다.
RETRIES = 4
BACKOFF_SEC = 2.0


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- http


def with_retry(fn, what: str):
    """연결 리셋/타임아웃만 재시도. 순차 실행이라 동시 요청은 생기지 않는다."""
    last_exc = None
    for attempt in range(1, RETRIES + 1):
        try:
            return fn()
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt < RETRIES:
                wait = BACKOFF_SEC * attempt
                log(
                    "  %s 연결 실패 (%d/%d) %s — %.0f초 후 재시도"
                    % (what, attempt, RETRIES, type(exc).__name__, wait)
                )
                time.sleep(wait)
    raise last_exc


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    # 세션 쿠키를 받아 둬야 내부 엔드포인트가 JSON을 돌려준다.
    with_retry(lambda: s.get(BASE + "/", timeout=TIMEOUT), "메인 페이지")
    return s


def post_json(session: requests.Session, path: str, params: dict, referer: str) -> dict:
    """betman 내부 XHR 재현. requestClient.js가 params에 _sbmInfo를 끼워 넣는다."""
    body = dict(params)
    body["_sbmInfo"] = {"_sbmInfo": {"debugMode": "false"}}
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": BASE,
        "Referer": referer,
    }
    res = with_retry(
        lambda: session.post(
            BASE + path, data=json.dumps(body), headers=headers, timeout=TIMEOUT
        ),
        path,
    )
    res.raise_for_status()
    ctype = res.headers.get("content-type", "")
    if "json" not in ctype.lower():
        # 차단되거나 로그인을 요구하면 HTML 에러 페이지가 돌아온다.
        raise ValueError("%s: JSON이 아닌 응답 (content-type=%r)" % (path, ctype))
    return res.json()


def buyable_games(session: requests.Session) -> dict:
    """현재 판매중인 게임 목록(토토+프로토) 원본 응답."""
    return post_json(
        session,
        "/buyPsblGame/inqCacheBuyAbleGameInfoList.do",
        {},
        referer=BASE + "/",
    )


# ---------------------------------------------------------------- format


def fmt_kst(epoch_ms: int) -> str:
    """epoch millis → '11/23(토) 19:30' (KST)."""
    dt = datetime.fromtimestamp(epoch_ms / 1000, tz=KST)
    return "%d/%d(%s) %02d:%02d" % (
        dt.month,
        dt.day,
        WEEKDAY_KR[dt.weekday()],
        dt.hour,
        dt.minute,
    )


def fmt_kst_short(epoch_ms: int) -> str:
    """epoch millis → '8/28 19:00' (KST). 배당 기준 시각 표시용."""
    dt = datetime.fromtimestamp(epoch_ms / 1000, tz=KST)
    return "%d/%d %02d:%02d" % (dt.month, dt.day, dt.hour, dt.minute)


def now_kst() -> datetime:
    return datetime.now(tz=KST)


def clean(value) -> str:
    return str(value).strip() if value is not None else ""


# ---------------------------------------------------------------- io


def write_json_if_changed(path: Path, payload: dict, label: str) -> bool:
    """updated(매 실행마다 바뀜)를 뺀 나머지가 같으면 파일을 건드리지 않는다."""
    old = None
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log("기존 %s를 읽지 못함, 새로 씀: %s" % (path.name, exc))

    def strip(d: dict) -> dict:
        return {k: v for k, v in d.items() if k not in ("updated", "updated_label")}

    if old is not None and strip(old) == strip(payload):
        log("제%s회차 — 내용 동일, 파일 유지 (커밋 없음)" % payload.get("round"))
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    prev = "제%s회차 → " % old["round"] if old and old.get("round") else ""
    log("%s 갱신: %s제%s회차" % (label, prev, payload.get("round")))
    return True
