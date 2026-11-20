"""검수기 정확도 시험: 정상 원고 1건 + 누락 7건 + 왜곡 10건.

python tests/run_eval.py  → 각 사례를 검수기가 잡았는지 표로 출력하고 tests/eval_result.md 저장
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from checker import check_all, load_json  # noqa: E402

base = load_json("demo_result.json")["result"]
photo_ok = [{"file": "현장1.jpg", "visible_text": "티링크모바일 통화 녹음 00:42"}]


def blog_replace(a: str, b: str):
    def f(r):
        assert a in r["blog"], a
        r["blog"] = r["blog"].replace(a, b, 1)
    return f


def add_sentence(s: str):
    return blog_replace("보안도 꼼꼼합니다.", s + " 보안도 꼼꼼합니다.")


CASES = [
    # (이름, 유형, 변형, 기대: "row:<id>" 실패 또는 "needs")
    ("정상 원고", "정상", None, "clean"),
    ("제목에서 필수 키워드 「업무자동화」 빠짐", "누락", blog_replace("통화요약 업무자동화,", "통화요약,"), "row:K"),
    ("보안(AES256) 문장 빠짐", "누락", blog_replace("녹취파일은 AES256으로 암호화되고 비밀번호는 SHA256으로 보호되며, 사용자별 접근권한을 따로 둘 수 있습니다. 〔F03〕", ""), "row:M11"),
    ("이미지 「직원별 통계」 빠짐", "누락", blog_replace("[이미지: 직원별 통계]", ""), "row:M9"),
    ("이미지 순서 뒤바뀜", "누락", lambda r: r.update(blog=r["blog"].replace("[이미지: 휴대폰 통화 화면]", "[TMP]").replace("[이미지: 인터넷전화 녹취 목록]", "[이미지: 휴대폰 통화 화면]").replace("[TMP]", "[이미지: 인터넷전화 녹취 목록]")), "row:M9"),
    ("하단 홈페이지·상담 문의 빠짐", "누락", lambda r: r.update(blog=r["blog"].split("홈페이지(www.tlinkcrm.com)")[0]), "row:F"),
    ("미결 상담 언급 빠짐", "누락", lambda r: r.update(blog=r["blog"].replace("미결 상담", "진행 상담").replace("미결 업무", "남은 업무")), "row:M4"),
    ("문자 90byte 초과", "누락", lambda r: r.update(sms="[티링크] 휴대폰·인터넷전화·PC폰 통화를 한곳에 녹음하고 AI가 자동으로 요약해 드립니다. 지금 상담받아 보세요. 1877-3836"), "row:S"),
    ("녹취 성공률 99%를 95%로 바꿈", "왜곡", add_sentence("녹취 성공률은 95%입니다. 〔F02〕"), "needs"),
    ("근거 없는 효과 수치 「상담 시간 30% 절감」", "왜곡", add_sentence("도입 후 상담 시간이 30% 줄었습니다."), "needs"),
    ("통역 60개 언어를 50개로 바꿈", "왜곡", add_sentence("PC폰은 50개 이상 언어를 통역합니다. 〔F22〕"), "needs"),
    ("없는 기능 「실시간 화상회의 녹화」", "왜곡", add_sentence("실시간 화상회의 녹화도 지원합니다."), "needs"),
    ("없는 기능 「카카오톡 상담 저장」", "왜곡", add_sentence("카카오톡 상담 내용도 함께 저장됩니다."), "needs"),
    ("존재하지 않는 근거 번호 F99", "왜곡", add_sentence("통화가 끝나면 요약이 만들어집니다. 〔F99〕"), "needs"),
    ("숫자와 근거가 어긋남 (한국전력 3,000석에 학교 근거)", "왜곡", add_sentence("한국전력 고객센터 3,000석에도 들어갔습니다. 〔F29〕"), "needs"),
    ("요금 3만원을 2만원으로 바꿈", "왜곡", add_sentence("A타입은 월 2만원입니다. 〔F16〕"), "needs"),
    ("본문에 개인 휴대폰 번호", "왜곡", add_sentence("담당자 직통 010-2481-7735로 연락 주세요."), "needs"),
    ("사진 속 글자에 고객 전화번호", "왜곡", "photo_pii", "needs"),
]


def run() -> list[dict]:
    out = []
    for name, kind, fn, expect in CASES:
        r = copy.deepcopy(base)
        photos = photo_ok
        if fn == "photo_pii":
            photos = [{"file": "현장2.jpg", "visible_text": "수신 010-2481-7735 김OO 고객"}]
        elif fn:
            fn(r)
        res = check_all(r, photos=photos)
        failed = {x["id"] for x in res["rows"] if not x["pass"]}
        if expect == "clean":
            ok = not failed and not res["needs_check"]
        elif expect == "needs":
            ok = bool(res["needs_check"])
        else:
            ok = expect.split(":")[1] in failed
        out.append({"name": name, "kind": kind, "ok": ok, "passed": f"{res['passed']}/{res['total']}", "needs": len(res["needs_check"])})
    return out


if __name__ == "__main__":
    rows = run()
    bad = [r for r in rows if r["kind"] != "정상"]
    caught = sum(r["ok"] for r in bad)
    normal_ok = all(r["ok"] for r in rows if r["kind"] == "정상")
    lines = ["# 검수기 정확도 시험 결과", "", f"- 문제를 심은 원고 {len(bad)}건 중 {caught}건 탐지 ({caught / len(bad) * 100:.0f}%)",
             f"- 정상 원고 오탐지: {'없음' if normal_ok else '있음'}", "", "| 사례 | 유형 | 결과 | 가이드라인 충족 | 확인 필요 |", "|---|---|---|---|---|"]
    for r in rows:
        mark = ("정상 통과" if r["ok"] else "오탐지") if r["kind"] == "정상" else ("탐지" if r["ok"] else "놓침")
        lines.append(f"| {r['name']} | {r['kind']} | {mark} | {r['passed']} | {r['needs']} |")
    text = "\n".join(lines)
    print(text)
    (ROOT / "tests" / "eval_result.md").write_text(text + "\n", encoding="utf-8")
