"""규칙 검수 (AI가 아닌 코드로 정확 일치 검사).

- 가이드라인 필수 키워드 / 첫 문단 키워드 / 리뷰 미션 11개 / 하단 정보
- 팩트락: 생성문 속 숫자가 팩트시트·가이드라인에 없으면 「확인 필요」
- 개인정보: 공식 상담번호 외 전화번호 패턴 감지
- 문자: SMS 90byte(한글 45자) 초과 여부
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DATA = Path(__file__).parent / "data"


def load_json(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def _has(text: str, term: str) -> bool:
    return _norm(term) in _norm(text)


def split_blog(blog: str) -> tuple[str, str, str, str]:
    """(제목, 첫 문단, 본문 전체, 마지막 문단) 반환. 첫 줄이 제목."""
    lines = [l for l in blog.strip().splitlines()]
    title = lines[0].lstrip("# ").strip() if lines else ""
    body = "\n".join(lines[1:]).strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    paras_text = [p for p in paras if not p.startswith("[이미지") and not p.startswith("#")]
    first = paras_text[0] if paras_text else ""
    # 마지막 문단: 하단 연락처/태그 앞의 마지막 본문 문단
    content_paras = [p for p in paras_text if not any(k in p for k in ("tlinkcrm.com", "1877-3836"))]
    last = content_paras[-1] if content_paras else ""
    return title, first, body, last


NUM_RE = re.compile(r"(?<![A-Za-z])(\d[\d,\.]*)\s*(?:여\s?)?(%|퍼센트|건|곳|개|석|만\s?원|원|분|초|배|명|년|회|시간|일|대|USER)?")


def _unit(u: str | None) -> str:
    u = (u or "").replace(" ", "")
    return "%" if u == "퍼센트" else u


def _fact_numbers(facts: dict, guide: dict) -> tuple[set[str], set[str]]:
    """(숫자만, 숫자+단위) 허용 목록. 단위가 붙은 숫자는 같은 단위로만 허용."""
    bare: set[str] = set()
    with_unit: set[str] = set()
    corpus = " ".join(f["text"] + " " + " ".join(f["numbers"]) for f in facts["facts"])
    corpus += " " + json.dumps(guide, ensure_ascii=False)
    for m in NUM_RE.finditer(corpus):
        n = m.group(1).rstrip(".,").replace(",", "")
        bare.add(n)
        with_unit.add(n + _unit(m.group(2)))
    return bare, with_unit
PHONE_RE = re.compile(r"\b0\d{1,2}[-\s.]?\d{3,4}[-\s.]?\d{4}\b|\b1[5-9]\d{2}-\d{4}\b")


def factlock(text: str, facts: dict, guide: dict) -> list[dict]:
    """팩트시트·가이드라인에 없는 숫자를 「확인 필요」로 반환."""
    bare, with_unit = _fact_numbers(facts, guide)
    issues = []
    scrubbed = PHONE_RE.sub(" ", text)
    scrubbed = re.sub(r"https?://\S+|www\.\S+|AES256|SHA256|M\d+|F\d+", " ", scrubbed)
    for m in NUM_RE.finditer(scrubbed):
        raw = m.group(1).rstrip(".,")
        n = raw.replace(",", "")
        u = _unit(m.group(2))
        if not n or (u and n + u in with_unit) or (not u and n in bare):
            continue
        # 순서 번호(1. 2. 3.)와 카드 번호 등 한 자리 서수는 허용
        if re.fullmatch(r"[1-9]", n) and (m.group(2) in (None, "", "대")):
            continue
        s, e = max(0, m.start() - 15), min(len(scrubbed), m.end() + 15)
        issues.append({"value": m.group(0).strip(), "context": scrubbed[s:e].replace("\n", " "), "reason": "팩트시트에 없는 숫자"})
    return issues


def pii_scan(text: str, guide: dict) -> list[str]:
    ok = set(guide.get("allowed_contact_numbers", []))
    return [p for p in PHONE_RE.findall(text) if p not in ok]


def sms_bytes(text: str) -> int:
    return len(text.encode("cp949", errors="replace"))


def check_blog(blog: str, guide: dict) -> list[dict]:
    title, first, body, last = split_blog(blog)
    full = title + "\n" + body
    rows = []
    for kw in guide["required_keywords"]:
        ok_t, ok_b = _has(title, kw), _has(body, kw)
        rows.append({"id": "K", "item": f"필수 키워드 「{kw}」 제목·본문", "pass": ok_t and ok_b,
                     "detail": f"제목 {'O' if ok_t else 'X'} / 본문 {'O' if ok_b else 'X'}"})
    for ms in guide["missions"]:
        t = ms["type"]
        if t == "first_paragraph":
            miss = [k for k in guide["first_paragraph_keywords"] if not (_has(title, k) or _has(first, k))]
            rows.append({"id": ms["id"], "item": ms["title"], "pass": not miss, "detail": "누락: " + ", ".join(miss) if miss else "4개 모두 포함"})
        elif t in ("terms", "conclusion"):
            target = last if t == "conclusion" else full
            miss = ["/".join(g) for g in ms["all_of"] if not any(_has(target, x) for x in g)]
            rows.append({"id": ms["id"], "item": ms["title"], "pass": not miss, "detail": "누락: " + ", ".join(miss) if miss else "충족"})
        elif t == "image_order":
            pos = [_norm(body).find(_norm("[이미지:" + x)) for x in ms["order"]]
            found = all(p >= 0 for p in pos)
            ordered = found and pos == sorted(pos)
            miss = [x for x, p in zip(ms["order"], pos) if p < 0]
            rows.append({"id": ms["id"], "item": ms["title"], "pass": ordered,
                         "detail": "순서대로 5종 포함" if ordered else ("누락: " + ", ".join(miss) if miss else "순서가 다름")})
    fmiss = ["/".join(g) for g in guide["footer"]["all_of"] if not any(_has(body, x) for x in g)]
    rows.append({"id": "F", "item": "하단 홈페이지·블로그·상담 문의", "pass": not fmiss, "detail": "누락: " + ", ".join(fmiss) if fmiss else "충족"})
    return rows


def check_all(result: dict, facts: dict | None = None, guide: dict | None = None) -> dict:
    """result = {"blog": str, "cards": [str]*4, "sms": str, "used_fact_ids": [..]}"""
    facts = facts or load_json("factsheet.json")
    guide = guide or load_json("guideline_2026_11.json")
    blog, cards, sms = result.get("blog", ""), result.get("cards", []), result.get("sms", "")
    rows = check_blog(blog, guide)
    nbytes = sms_bytes(sms)
    rows.append({"id": "S", "item": f"문자 SMS {guide['sms_max_bytes']}byte 이하", "pass": nbytes <= guide["sms_max_bytes"], "detail": f"{nbytes}byte"})
    rows.append({"id": "C", "item": "카드뉴스 4컷", "pass": len(cards) == 4, "detail": f"{len(cards)}컷"})
    known = {f["id"] for f in facts["facts"]}
    bad_ids = [i for i in result.get("used_fact_ids", []) if i not in known]
    all_text = "\n".join([blog, *cards, sms])
    needs = []
    for i in bad_ids:
        needs.append({"value": i, "context": "", "reason": "존재하지 않는 근거 ID"})
    for chan, txt in (("블로그", blog), ("카드뉴스", "\n".join(cards)), ("문자", sms)):
        for it in factlock(txt, facts, guide):
            it["channel"] = chan
            needs.append(it)
    for p in pii_scan(all_text, guide):
        needs.append({"value": p, "context": "", "reason": "개인 전화번호 의심", "channel": "전체"})
    passed = sum(r["pass"] for r in rows)
    return {"rows": rows, "passed": passed, "total": len(rows), "needs_check": needs,
            "copy_enabled": not needs}


if __name__ == "__main__":
    import sys
    res = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = check_all(res)
    for r in out["rows"]:
        print(("PASS" if r["pass"] else "FAIL"), r["id"], r["item"], "-", r["detail"])
    print(f"\n충족 {out['passed']}/{out['total']}, 확인 필요 {len(out['needs_check'])}건")
    for n in out["needs_check"]:
        print("  확인 필요:", n)
