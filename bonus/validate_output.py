"""LLM 답변 초안 자동 검사기.

정책 시트에 근거가 없는 금액·비율이 '1) 답변 초안'에 들어갔는지(환각 의심),
4단 출력 형식과 문자 채널 글자 수를 지켰는지 검사한다.

사용법:
    python bonus/validate_output.py <답변파일> [--policy templates/policy_sheet.md]
                                     [--sms] [--extra 400000 500000]
"""
import argparse
import re
import sys
from fractions import Fraction
from itertools import product

SECTIONS = ["## 1) 답변 초안", "## 2) 근거 정책", "## 3) 확인 필요 항목", "## 4) 내부 메모"]
SMS_LIMIT = 90

# "28만 8천원", "32만원", "288,000원", "3만원"
MONEY_RE = re.compile(r"(\d+)\s*만(?:\s*(\d+)\s*천)?\s*원|(\d{1,3}(?:,\d{3})+|\d{4,})\s*원")
PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
FRACTION_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


def extract_money(text):
    amounts = set()
    for man, cheon, won in MONEY_RE.findall(text):
        if man:
            amounts.add(int(man) * 10000 + (int(cheon) * 1000 if cheon else 0))
        else:
            amounts.add(int(won.replace(",", "")))
    return amounts


def extract_percents(text):
    return {Fraction(p) / 100 for p in PERCENT_RE.findall(text)}


def allowed_amounts(policy_text, extra):
    """정책 금액 + 정책 비율(할인율·환불 비율)로 계산 가능한 금액 + 사용자 제공 금액."""
    base = extract_money(policy_text) | set(extra)
    ratios = extract_percents(policy_text)
    ratios |= {Fraction(int(a), int(b)) for a, b in FRACTION_RE.findall(policy_text) if int(b)}
    allowed = set(base)
    for amount, r in product(base, ratios):
        allowed.add(int(amount * r))
        allowed.add(int(amount * (1 - r)))
    return allowed, ratios


def split_sections(text):
    parts = {}
    positions = [(text.find(s), s) for s in SECTIONS if s in text]
    positions.sort()
    for i, (pos, name) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        parts[name] = text[pos + len(name):end].strip()
    return parts


def validate(output_text, policy_text, sms=False, extra=()):
    issues = []
    parts = split_sections(output_text)

    missing = [s for s in SECTIONS if s not in parts]
    if missing:
        issues.append(f"[형식] 누락된 섹션: {', '.join(missing)}")

    draft = parts.get(SECTIONS[0], "")
    if sms:
        body = draft.splitlines()[0] if draft else ""
        if len(body) > SMS_LIMIT:
            issues.append(f"[채널] 문자 {len(body)}자 > {SMS_LIMIT}자")

    allowed, ratios = allowed_amounts(policy_text, extra)
    for amount in sorted(extract_money(draft) - allowed):
        issues.append(f"[환각 의심] 정책에서 도출되지 않는 금액: {amount:,}원")
    for pct in sorted(extract_percents(draft) - ratios):
        issues.append(f"[환각 의심] 정책에 없는 비율: {float(pct * 100):g}%")

    if draft and not re.search(r"P\d", parts.get(SECTIONS[1], "")):
        issues.append("[근거] 2) 근거 정책에 조항 번호(P1, P2-3 등)가 없음")
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output")
    parser.add_argument("--policy", default="templates/policy_sheet.md")
    parser.add_argument("--sms", action="store_true", help="문자 채널(90자) 검사")
    parser.add_argument("--extra", nargs="*", type=int, default=[],
                        help="대화 중 사용자가 제공한 금액(원 단위), 예: 정책 변경분")
    args = parser.parse_args()

    with open(args.output, encoding="utf-8") as f:
        output_text = f.read()
    with open(args.policy, encoding="utf-8") as f:
        policy_text = f.read()

    issues = validate(output_text, policy_text, args.sms, args.extra)
    if issues:
        print("FAIL")
        for issue in issues:
            print(" -", issue)
        sys.exit(1)
    print("PASS")


if __name__ == "__main__":
    main()
