"""규칙 검수 (AI가 아닌 코드로 검사).

1. 가이드라인: 필수 키워드, 첫 문단 키워드, 리뷰 미션 11개(자동/사람 확인 구분), 하단 정보, SMS 90byte
2. 팩트락(문장 단위): 제품 주장 문장마다 〔F05〕 같은 근거 번호가 있어야 함.
   - 근거 번호 없는 제품 주장 → 확인 필요
   - 없는 근거 번호 → 확인 필요
   - 근거 문장에 없는 숫자(예: 99%를 95%로) → 확인 필요
   - 팩트시트 어디에도 없는 숫자 → 확인 필요
3. 개인정보: 생성문과 사진 속 글자(AI가 읽어 낸 텍스트)에서 공식 상담번호 외 전화번호 패턴 검사
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DATA = Path(__file__).parent / "data"
TAG_RE = re.compile(r"〔(F\d{2,3}|G)〕")  # G = 월간 가이드라인이 요구한 문장
NUM_RE = re.compile(r"(?<![A-Za-z])(\d[\d,\.]*)\s*(?:여\s?)?(%|퍼센트|건|곳|개|석|만\s?원|원|분|초|배|명|년|회|시간|일|대|USER)?")
PHONE_RE = re.compile(r"(?<!\d)0\d{1,2}[-\s.]?\d{3,4}[-\s.]?\d{4}(?!\d)|(?<!\d)1[5-9]\d{2}-\d{4}(?!\d)")


def load_json(name: str) -> dict:
    """data/ 폴더에 없으면 앱 폴더 바로 아래에서도 찾는다 (웹 업로드로 폴더가 빠졌을 때 대비)."""
    for p in (DATA / name, DATA.parent / name):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"{name} 파일이 없습니다. GitHub 저장소에 data 폴더 또는 {name}을 올려 주세요.")


def clean(text: str) -> str:
    """근거 번호 태그를 지운 최종 게시용 텍스트."""
    return re.sub(r"\s*〔(?:F\d{2,3}|G)〕", "", text)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def _has(text: str, term: str) -> bool:
    return _norm(term) in _norm(clean(text))


def _unit(u: str | None) -> str:
    u = (u or "").replace(" ", "")
    return "%" if u == "퍼센트" else u


def _nums(text: str) -> list[tuple[str, str, str]]:
    """(숫자, 단위, 원문) 목록. URL·전화번호·AES256 등 제외."""
    t = PHONE_RE.sub(" ", text)
    t = re.sub(r"https?://\S+|www\.\S+|AES256|SHA256|〔(?:F\d+|G)〕|\bM\d+\b", " ", t)
    out = []
    for m in NUM_RE.finditer(t):
        n = m.group(1).rstrip(".,").replace(",", "")
        if n:
            out.append((n, _unit(m.group(2)), m.group(0).strip()))
    return out


def _allowed(text: str) -> tuple[set[str], set[str]]:
    bare, unit = set(), set()
    for n, u, _ in _nums(text):
        bare.add(n)
        unit.add(n + u)
    return bare, unit


def _num_ok(n: str, u: str, bare: set[str], unit: set[str]) -> bool:
    return bool((u and n + u in unit) or (not u and n in bare))


def split_blog(blog: str) -> tuple[str, str, str, str]:
    """(제목, 첫 문단, 본문 전체, 마지막 본문 문단). 첫 줄이 제목."""
    lines = blog.strip().splitlines()
    title = lines[0].lstrip("# ").strip() if lines else ""
    body = "\n".join(lines[1:]).strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    text_paras = [p for p in paras if not p.startswith("[이미지") and not p.startswith("#")]
    first = text_paras[0] if text_paras else ""
    content = [p for p in text_paras if not any(k in p for k in ("tlinkcrm.com", "1877-3836"))]
    last = content[-1] if content else ""
    return title, first, body, last


def sentences(text: str) -> list[str]:
    """검사 대상 문장: 이미지 자리, 태그 줄, 하단 연락처, 번호 소제목 줄은 제외."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("[이미지") or s.startswith("#") or "tlinkcrm.com" in s or s.startswith("상담 문의"):
            continue
        if re.fullmatch(r"\d+\.\s*[^.。!?]{0,30}", s):  # 「2. 휴대폰·인터넷전화 동시 녹음」 같은 소제목
            continue
        # 문장 끝 마침표 뒤에 붙은 근거 번호를 그 문장 안으로 옮긴 뒤 문장 단위로 자른다
        s = re.sub(r"([.!?。])((?:\s*〔(?:F\d{2,3}|G)〕)+)", lambda m: m.group(2) + m.group(1), s)
        pieces = [x.strip() for x in re.split(r"(?<=[.!?。])\s+", s) if x.strip()]
        for x in pieces:
            # 「... 1877-3836 〔F05〕」처럼 연락처 뒤에 붙은 근거 번호는 앞 문장의 근거로 본다
            rest = PHONE_RE.sub("", clean(x)).strip(" .!?")
            if out and TAG_RE.search(x) and len(rest) < 4:
                out[-1] += " " + " ".join(f"〔{t}〕" for t in TAG_RE.findall(x))
            else:
                out.append(x)
    return out


def check_guideline(blog: str, guide: dict) -> list[dict]:
    title, first, body, last = split_blog(blog)
    full = title + "\n" + body
    rows = []
    for kw in guide["required_keywords"]:
        ok_t, ok_b = _has(title, kw), _has(body, kw)
        rows.append({"id": "K", "item": f"필수 키워드 「{kw}」 제목·본문", "pass": ok_t and ok_b, "manual": False,
                     "detail": f"제목 {'O' if ok_t else 'X'} / 본문 {'O' if ok_b else 'X'}"})
    for ms in guide["missions"]:
        t, manual = ms["type"], ms.get("mode") == "semantic"
        if t == "first_paragraph":
            miss = [k for k in guide["first_paragraph_keywords"] if not (_has(title, k) or _has(first, k))]
            ok, detail = not miss, ("누락: " + ", ".join(miss)) if miss else "4개 모두 포함"
        elif t in ("terms", "conclusion"):
            target = last if t == "conclusion" else full
            miss = ["/".join(g) for g in ms["all_of"] if not any(_has(target, x) for x in g)]
            ok, detail = not miss, ("누락: " + ", ".join(miss)) if miss else "핵심어 충족"
        else:  # image_order
            nb = _norm(body)
            pos = [nb.find(_norm("[이미지:" + x)) for x in ms["order"]]
            miss = [x for x, p in zip(ms["order"], pos) if p < 0]
            ok = not miss and pos == sorted(pos)
            detail = "순서대로 5종 포함" if ok else (("누락: " + ", ".join(miss)) if miss else "순서가 다름")
        if manual and ok:
            detail += " · 의미는 사람 확인"
        rows.append({"id": ms["id"], "item": ms["title"], "pass": ok, "manual": manual, "detail": detail})
    fmiss = ["/".join(g) for g in guide["footer"]["all_of"] if not any(_has(body, x) for x in g)]
    rows.append({"id": "F", "item": "하단 홈페이지·블로그·상담 문의", "pass": not fmiss, "manual": False,
                 "detail": ("누락: " + ", ".join(fmiss)) if fmiss else "충족"})
    return rows


def factlock(text: str, channel: str, facts: dict, guide: dict, require_tags: bool = True) -> list[dict]:
    by_id = {f["id"]: f for f in facts["facts"]}
    all_corpus = " ".join(f["text"] + " " + " ".join(f["numbers"]) for f in facts["facts"]) + " " + json.dumps(guide, ensure_ascii=False)
    g_bare, g_unit = _allowed(all_corpus)
    terms = guide.get("claim_terms", [])
    issues = []
    for s in sentences(text):
        ids = TAG_RE.findall(s)
        shown = clean(s)
        bad = [i for i in ids if i != "G" and i not in by_id]
        for i in bad:
            issues.append({"channel": channel, "value": i, "context": shown, "reason": "존재하지 않는 근거 번호"})
        nums = [x for x in _nums(s) if not (re.fullmatch(r"[1-9]", x[0]) and not x[1])]  # 한 자리 서수 제외
        good = [by_id[i] for i in ids if i in by_id]
        if good or "G" in ids:
            src = " ".join(f["text"] + " " + " ".join(f["numbers"]) for f in good)
            if "G" in ids:
                src += " " + json.dumps(guide, ensure_ascii=False)
            b, u = _allowed(src)
            for n, un, raw in nums:
                if not _num_ok(n, un, b, u):
                    why = "근거 문장과 맞지 않는 숫자" if _num_ok(n, un, g_bare, g_unit) else "팩트시트에 없는 숫자"
                    issues.append({"channel": channel, "value": raw, "context": shown, "reason": f"{why} ({', '.join(ids)})"})
            continue
        for n, un, raw in nums:
            if not _num_ok(n, un, g_bare, g_unit):
                issues.append({"channel": channel, "value": raw, "context": shown, "reason": "팩트시트에 없는 숫자"})
        if require_tags and not ids and any(t.lower() in shown.lower() for t in terms):
            issues.append({"channel": channel, "value": "근거 번호 없음", "context": shown, "reason": "근거 번호 없는 제품 주장"})
    return issues


def mask(phone: str) -> str:
    d = re.sub(r"\D", "", phone)
    return d[:3] + "-" + d[3:5] + "**-****" if len(d) >= 9 else "***"


def pii_scan(text: str, guide: dict) -> list[str]:
    ok = set(guide.get("allowed_contact_numbers", []))
    return [p for p in PHONE_RE.findall(text) if p not in ok]


def sms_bytes(text: str) -> int:
    return len(clean(text).encode("cp949", errors="replace"))


def check_all(result: dict, facts: dict | None = None, guide: dict | None = None,
              photos: list[dict] | None = None, require_tags: bool = True) -> dict:
    """result = {"blog", "cards"[4], "sms"}; photos = 분석 결과의 photos(visible_text 포함)."""
    facts = facts or load_json("factsheet.json")
    guide = guide or load_json("guideline_2026_11.json")
    blog, cards, sms = result.get("blog", ""), result.get("cards", []), result.get("sms", "")
    rows = check_guideline(blog, guide)
    nb = sms_bytes(sms)
    rows.append({"id": "S", "item": f"문자 SMS {guide['sms_max_bytes']}byte 이하", "pass": nb <= guide["sms_max_bytes"], "manual": False, "detail": f"{nb}byte"})
    rows.append({"id": "C", "item": "카드뉴스 4컷", "pass": len(cards) == 4, "manual": False, "detail": f"{len(cards)}컷"})
    needs = []
    title, _, body, _ = split_blog(blog)
    needs += factlock(body, "블로그", facts, guide, require_tags)
    needs += factlock("\n".join(cards), "카드뉴스", facts, guide, require_tags)
    needs += factlock(sms, "문자", facts, guide, require_tags)
    for p in pii_scan("\n".join([blog, *cards, sms]), guide):
        needs.append({"channel": "생성문", "value": mask(p), "context": "", "reason": "개인 전화번호 의심"})
    for ph in photos or []:
        for p in pii_scan(ph.get("visible_text", ""), guide):
            needs.append({"channel": f"사진 {ph.get('file', '')}", "value": mask(p), "context": "사진 속 글자에서 발견",
                          "reason": "사진에 전화번호 노출 · 가림 처리 후 게시"})
    for i, n in enumerate(needs):
        n["key"] = f"n{i}"
    return {"rows": rows, "passed": sum(r["pass"] for r in rows), "total": len(rows),
            "needs_check": needs, "copy_enabled": not needs}


if __name__ == "__main__":
    import sys
    res = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = check_all(res, photos=res.get("photos"))
    for r in out["rows"]:
        print(("PASS" if r["pass"] else "FAIL"), r["id"], r["item"], "-", r["detail"])
    print(f"\n충족 {out['passed']}/{out['total']}, 확인 필요 {len(out['needs_check'])}건")
    for n in out["needs_check"]:
        print("  확인 필요:", n["channel"], "|", n["value"], "|", n["reason"], "|", n["context"][:60])
