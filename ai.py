"""Google Gemini API 호출: ① 사진 분석 + 차별점 매칭, ② 채널별 콘텐츠 생성.

무료 등급 키(Google AI Studio)로 동작한다. 모델은 GEMINI_MODEL로 바꿀 수 있고,
첫 모델을 쓸 수 없으면 다음 모델로 자동 재시도한다.
"""
from __future__ import annotations

import io
import json
import os

from google import genai
from google.genai import types
from PIL import Image

MODELS = [m for m in [os.getenv("GEMINI_MODEL"), "gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash"] if m]

SCENES = {
    "phone_screen": "휴대폰 통화·녹음 화면",
    "voip_phone": "사무실 인터넷전화기",
    "pc_softphone": "PC 소프트폰 화면",
    "server_rack": "녹취서버·통신 랙",
    "call_center_seats": "콜센터·상담석",
    "dashboard_screen": "관리 화면·리포트·대시보드",
    "office_install": "사무실 회선·구내 통신 공사 현장",
    "meeting": "대면 상담·미팅 현장",
    "other": "기타",
}

ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["photos", "matched_facts"],
    "properties": {
        "photos": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["file", "scene_tags", "visible_text", "pii"],
            "properties": {
                "file": {"type": "string"},
                "visible_text": {"type": "string"},
                "scene_tags": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["tag", "label", "confidence"],
                    "properties": {
                        "tag": {"type": "string", "enum": list(SCENES)},
                        "label": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["high", "low"]}}}},
                "pii": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["where", "action"],
                    "properties": {"where": {"type": "string"}, "action": {"type": "string"}}}}}}},
        "matched_facts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["fact_id", "why"],
            "properties": {"fact_id": {"type": "string"}, "why": {"type": "string"}}}},
    },
}

CONTENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["blog", "cards", "sms", "used_fact_ids"],
    "properties": {
        "blog": {"type": "string"},
        "cards": {"type": "array", "items": {"type": "string"}},
        "sms": {"type": "string"},
        "used_fact_ids": {"type": "array", "items": {"type": "string"}},
    },
}

ANALYSIS_SYSTEM = """너는 티링크(녹취·CRM·인터넷전화 솔루션 기업)의 홍보 담당을 돕는 현장 사진 분석가다.
- 각 사진을 정해진 장면 태그로 분류한다. 사진만으로 확실하지 않으면 confidence를 low로 둔다. 추측으로 high를 주지 않는다.
- 사진 속에서 읽을 수 있는 글자(화면 문구, 숫자, 전화번호, 이름 등)를 visible_text에 보이는 그대로 모두 적는다. 없으면 빈 문자열. 이 글자는 코드가 전화번호 패턴으로 한 번 더 검사한다.
- 사진 속 사람 얼굴, 고객 이름, 전화번호, 차량 번호처럼 게시하면 안 되는 정보가 보이면 pii에 「어느 위치에 무엇이 보이는지(노출 글자 일부 포함)」와 「가림 처리 권고」를 적는다. 없으면 빈 배열.
- 제공된 팩트시트에서 사진 장면·업종·제품과 가장 잘 맞는 기술적 차별점 3개를 fact_id로 고르고, 왜 이 사진과 연결되는지 한 문장으로 쓴다. 팩트시트에 없는 ID는 쓰지 않는다."""

CONTENT_SYSTEM = """너는 티링크 비즈레코딩 홍보 콘텐츠 작성자다. 아래 규칙을 반드시 지킨다.
[사실 규칙]
- 제품 설명과 숫자는 제공된 팩트시트 문장에 있는 것만 쓴다. 팩트시트에 없는 효과 수치(예: 몇 % 절감), 고객사 이름, 기능은 만들지 않는다.
- 제품 기능·숫자·실적을 말하는 문장은 마침표 바로 뒤에 근거 팩트 번호를 〔F05〕처럼 붙인다. 여러 개면 〔F05〕〔F07〕.
- 가이드라인이 요구해서 쓴 문장(사용 후기 경험, 결론 문장 등)은 〔G〕를 붙인다.
- 근거 번호가 없는 문장에는 제품 기능을 쓰지 않는다. 근거 번호는 게시 전에 자동으로 지워진다.
- 사용한 팩트 ID를 used_fact_ids에 모두 적는다.
- 개인 전화번호, 사람 이름은 쓰지 않는다. 연락처는 가이드라인 하단 정보만 쓴다.
[블로그 원고 blog]
- 첫 줄은 제목이다. 제목에 필수 키워드 3개를 모두 넣는다.
- 제목 또는 첫 문단에 첫 문단 키워드 4개를 자연스럽게 모두 넣는다. 본문에도 필수 키워드 3개를 다시 쓴다.
- 가이드라인의 추천 본문 구성 5단을 번호 소제목으로 쓴다. 미션 11개를 모두 충족한다.
- 실제 사용 후기 말투(직접 통화 한 건을 녹음해 본 경험)로 쓴다.
- 이미지 자리는 [이미지: 휴대폰 통화 화면], [이미지: 인터넷전화 녹취 목록], [이미지: AI 통화요약], [이미지: 직원별 통계], [이미지: 종합 리포트] 를 이 순서대로 각각 한 줄에 둔다.
- 마지막 본문 문단은 「영업 활동을 자동으로 기록하고 경영에 필요한 정보로 정리해 주는 기업용 영업관리 솔루션」이라는 결론을 담는다.
- 그 뒤에 가이드라인 하단 정보(홈페이지, 블로그, 상담 문의)를 그대로 넣고, 마지막 줄에 태그를 넣는다.
- 문단 사이는 빈 줄로 구분한다.
[카드뉴스 cards] 정확히 4개. 각 40자 안팎. 1컷 문제 제기, 2~3컷 사진과 연결된 차별점, 4컷 행동 유도.
[문자 sms] 근거 번호를 뺀 본문이 SMS 90byte(한글 45자) 이하. [티링크]로 시작."""

PLAIN_SYSTEM = """너는 마케팅 카피라이터다. 제공된 제품 자료와 가이드라인을 참고해 네이버 블로그 원고(첫 줄 제목), 인스타 카드뉴스 4컷 문구, 고객 문자 문구를 써라. used_fact_ids는 빈 배열로 둔다."""


def make_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def _img_part(data: bytes) -> types.Part:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((1568, 1568))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")


def _call(client: genai.Client, system: str, content: list, schema: dict, max_tokens: int) -> dict:
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_json_schema=schema,
        max_output_tokens=max_tokens,
        temperature=0.4,
    )
    last_err: Exception | None = None
    for model in MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=content, config=cfg)
        except Exception as e:  # 모델 이름 없음(404) 등은 다음 모델로
            last_err = e
            if "404" in str(e) or "not found" in str(e).lower():
                continue
            if "API_KEY_INVALID" in str(e) or "API key not valid" in str(e):
                raise RuntimeError("API 키가 올바르지 않아요. Streamlit Secrets의 GEMINI_API_KEY를 확인해 주세요.") from e
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                raise RuntimeError("무료 사용량 한도에 걸렸어요. 1분 뒤 다시 눌러 주세요.") from e
            raise
        text = resp.text or ""
        if not text.strip():
            raise RuntimeError("AI가 빈 응답을 보냈어요. 다시 시도해 주세요.")
        return json.loads(text)
    raise RuntimeError(f"사용 가능한 Gemini 모델을 찾지 못했어요: {last_err}")


def candidate_facts(facts: dict, product: str, industry: str) -> list[dict]:
    def ok(lst, v):
        return "*" in lst or v in lst
    return [f for f in facts["facts"] if ok(f["products"], product) or ok(f["industries"], industry)]


def analyze(client, photos: list[tuple[str, bytes]], product: str, industry: str, facts: dict) -> dict:
    cands = candidate_facts(facts, product, industry)
    content: list = []
    for name, data in photos:
        content.append(f"사진 파일명: {name}")
        content.append(_img_part(data))
    content.append((
        f"제품: {product}\n고객 업종: {industry}\n장면 태그 목록: {json.dumps(SCENES, ensure_ascii=False)}\n"
        f"팩트시트 후보:\n{json.dumps([{'id': f['id'], 'text': f['text'], 'scenes': f['scenes']} for f in cands], ensure_ascii=False)}"))
    return _call(client, ANALYSIS_SYSTEM, content, ANALYSIS_SCHEMA, 4000)


def _scenes_only(analysis: dict) -> list[dict]:
    """사진 속 글자(개인정보 가능)는 생성 단계로 넘기지 않는다."""
    return [{"file": p["file"], "scene_tags": p["scene_tags"]} for p in analysis.get("photos", [])]


def generate_plain(client, analysis: dict, product: str, industry: str, facts: dict, guide: dict) -> dict:
    """비교 실험용: 규칙·근거 번호 없이 같은 자료만 주는 일반 프롬프트."""
    text = (f"제품: {product}\n고객 업종: {industry}\n사진 분석 결과: {json.dumps(_scenes_only(analysis), ensure_ascii=False)}\n"
            f"제품 자료: {json.dumps([f['text'] for f in facts['facts']], ensure_ascii=False)}\n"
            f"가이드라인: {json.dumps(guide, ensure_ascii=False)}")
    return _call(client, PLAIN_SYSTEM, [text], CONTENT_SCHEMA, 8192)


def generate(client, analysis: dict, product: str, industry: str, facts: dict, guide: dict,
             feedback: list[str] | None = None) -> dict:
    by_id = {f["id"]: f for f in facts["facts"]}
    matched = [m["fact_id"] for m in analysis.get("matched_facts", []) if m["fact_id"] in by_id]
    cands = candidate_facts(facts, product, industry)
    text = (
        f"제품: {product}\n고객 업종: {industry}\n"
        f"사진 분석 결과: {json.dumps(_scenes_only(analysis), ensure_ascii=False)}\n"
        f"사진과 매칭된 핵심 차별점(반드시 강조): {json.dumps([by_id[i] for i in matched], ensure_ascii=False)}\n"
        f"사용 가능한 팩트시트 전체: {json.dumps([{'id': f['id'], 'text': f['text']} for f in cands], ensure_ascii=False)}\n"
        f"가이드라인: {json.dumps(guide, ensure_ascii=False)}"
    )
    if feedback:
        text += "\n\n직전 결과에서 검수에 실패한 항목입니다. 이 항목만 고쳐 다시 쓰세요:\n- " + "\n- ".join(feedback)
    return _call(client, CONTENT_SYSTEM, [text], CONTENT_SCHEMA, 8192)
