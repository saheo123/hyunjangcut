"""현장컷 홍보메이커 (Streamlit)."""
from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

from checker import check_all, load_json, sms_bytes

ROOT = Path(__file__).parent
LOG = ROOT / "logs" / "history.csv"
PRODUCTS = {"A": "비즈레코딩 A타입 (고객관리·녹취·STT 요약·일일보고서)", "B": "비즈레코딩 B타입", "C": "비즈레코딩 C타입 (녹취)",
            "mobile": "휴대폰 녹취 (티링크모바일)", "pcphone": "PC폰 (TlinkPhone)", "report": "종합리포트 옵션"}
INDUSTRIES = {"sales_org": "영업조직", "callcenter": "콜센터", "hospital": "병원", "school": "학교", "travel": "여행사", "public": "공공기관", "finance": "금융"}

st.set_page_config(page_title="현장컷 홍보메이커", page_icon="📸", layout="wide")
facts, guide = load_json("factsheet.json"), load_json("guideline_2026_11.json")
by_id = {f["id"]: f for f in facts["facts"]}


def api_key() -> str | None:
    try:
        return st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    except Exception:
        return os.getenv("GEMINI_API_KEY")


def log_row(row: dict) -> None:
    LOG.parent.mkdir(exist_ok=True)
    new = not LOG.exists()
    with LOG.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


with st.sidebar:
    st.header("설정")
    demo = st.toggle("데모 모드 (저장된 예시 결과)", value=not api_key())
    st.caption(f"가이드라인: {guide['month']} · 팩트시트 {len(facts['facts'])}개 문장")
    st.caption("숫자·주장은 팩트시트에 있는 것만 쓰고, 없으면 「확인 필요」로 표시합니다.")

st.title("📸 현장컷 홍보메이커")
st.write("현장 사진과 제품만 고르면, 티링크 공식 자료에 근거한 블로그·카드뉴스·문자를 만들고 가이드라인 준수 여부까지 검수합니다.")

c1, c2, c3 = st.columns([2, 1, 1])
photos = c1.file_uploader("현장 사진 (1~5장)", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
product = c2.selectbox("제품", list(PRODUCTS), format_func=PRODUCTS.get)
industry = c3.selectbox("고객 업종", list(INDUSTRIES), format_func=INDUSTRIES.get)
if photos:
    st.image([p.getvalue() for p in photos[:5]], width=160)

if st.button("홍보 콘텐츠 만들기", type="primary", disabled=not (photos or demo)):
    t0 = time.time()
    if demo:
        d = load_json("demo_result.json")
        st.session_state.update(analysis=d["analysis"], result=d["result"], t_an=0.0, t_gen=0.0)
    else:
        from ai import analyze, generate, make_client
        client = make_client(api_key())
        try:
            with st.status("① 사진 분석과 차별점 매칭 중...") as s:
                an = analyze(client, [(p.name, p.getvalue()) for p in photos[:5]], product, industry, facts)
                t1 = time.time()
                s.update(label="② 블로그·카드뉴스·문자 생성 중...")
                res = generate(client, an, product, industry, facts, guide)
                t2 = time.time()
                s.update(label="완료", state="complete")
            st.session_state.update(analysis=an, result=res, t_an=t1 - t0, t_gen=t2 - t1)
        except Exception as e:  # 화면에 원인 표시
            st.error(f"생성 실패: {e}")
            st.stop()
    st.session_state.logged = False

if "result" in st.session_state:
    an, res = st.session_state.analysis, st.session_state.result
    st.divider()
    st.subheader("① 사진 분석 → 기술적 차별점")
    if st.session_state.t_an:
        st.caption(f"사진 분석 {st.session_state.t_an:.1f}초 · 콘텐츠 생성 {st.session_state.t_gen:.1f}초")
    pc = st.columns(max(1, len(an["photos"])))
    for col, ph in zip(pc, an["photos"]):
        with col:
            st.markdown(f"**{ph['file']}**")
            for t in ph["scene_tags"]:
                st.markdown(f"- {t['label']}" + ("" if t["confidence"] == "high" else " · :orange[확인 필요]"))
            for p in ph["pii"]:
                st.warning(f"개인정보 의심: {p['where']} → {p['action']}")
    fc = st.columns(3)
    for col, m in zip(fc, an["matched_facts"][:3]):
        f = by_id.get(m["fact_id"])
        with col.container(border=True):
            if f:
                st.markdown(f"**{f['text']}**")
                st.caption(f"근거: {f['source']} p.{f['page']} ({f['id']})")
                st.write(m["why"])
            else:
                st.error(f"{m['fact_id']}: 팩트시트에 없는 근거 · 확인 필요")

    st.subheader("② 채널별 콘텐츠")
    t1, t2, t3 = st.tabs(["블로그 원고", "카드뉴스 4컷", "문자"])
    res["blog"] = t1.text_area("블로그", res["blog"], height=520, label_visibility="collapsed")
    with t2:
        cols = st.columns(4)
        for i, col in enumerate(cols):
            if i < len(res["cards"]):
                res["cards"][i] = col.text_area(f"{i+1}컷", res["cards"][i], height=160)
    res["sms"] = t3.text_input("문자", res["sms"])
    t3.caption(f"{sms_bytes(res['sms'])} / {guide['sms_max_bytes']} byte")

    st.subheader("③ 가이드라인 자동 검수 + 팩트락")
    chk = check_all(res, facts, guide)
    m1, m2 = st.columns(2)
    m1.metric("가이드라인 항목 충족", f"{chk['passed']} / {chk['total']}")
    m2.metric("확인 필요", f"{len(chk['needs_check'])}건")
    for r in chk["rows"]:
        st.markdown(("✅ " if r["pass"] else "❌ ") + f"**{r['item']}** · {r['detail']}")
    for n in chk["needs_check"]:
        st.error(f"확인 필요 [{n.get('channel', '')}] {n['value']} · {n['reason']} · {n.get('context', '')}")

    fails = [f"{r['item']} ({r['detail']})" for r in chk["rows"] if not r["pass"]] + \
            [f"{n['value']}: {n['reason']} → 팩트시트 문장으로 바꾸거나 삭제" for n in chk["needs_check"]]
    b1, b2 = st.columns(2)
    if b1.button("실패 항목만 AI로 다시 쓰기", disabled=demo or not fails):
        from ai import generate, make_client
        with st.spinner("다시 쓰는 중..."):
            try:
                st.session_state.result = generate(make_client(api_key()), an, product, industry, facts, guide, fails)
            except Exception as e:
                st.error(f"다시 쓰기 실패: {e}")
                st.stop()
        st.rerun()
    bundle = f"{res['blog']}\n\n---카드뉴스---\n" + "\n".join(res["cards"]) + f"\n\n---문자---\n{res['sms']}"
    b2.download_button("최종 원고 내려받기", bundle, file_name="tlink_promo.txt", disabled=not chk["copy_enabled"],
                       help="「확인 필요」가 0건일 때만 활성화됩니다.")
    if not st.session_state.get("logged"):
        log_row({"time": datetime.now().isoformat(timespec="seconds"), "demo": demo, "product": product, "industry": industry,
                 "photos": len(an["photos"]), "passed": chk["passed"], "total": chk["total"], "needs_check": len(chk["needs_check"]),
                 "sec_analyze": round(st.session_state.t_an, 1), "sec_generate": round(st.session_state.t_gen, 1)})
        st.session_state.logged = True
