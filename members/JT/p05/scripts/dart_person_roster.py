"""OpenDART로 대주주·CEO 대상자 명부를 검증해 새 CSV로 저장한다.

- 입력: 프로젝트 .env의 DART_API_KEY (값은 출력·저장하지 않는다)
- 출력:
  data/dart_raw/<기업>_<api>.json        응답 중 분석 대상(대주주·CEO)과 그 변동 공시 항목만 저장
                                         (그 밖의 임원·주주·공시는 저장하지 않는다)
  data/person_target_roster_dart_<AS_OF>.csv  검증된 대상자 명부
- 1단계 명부 양식(person_target_roster_template.csv)은 쓰지 않는다."""
from pathlib import Path
import io
import json
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd
import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_DIR / "data" / "dart_raw"
AS_OF = "2026-10-27"           # 설계 문서의 기준일. 팀 확정 전 잠정값
BSNS_YEAR = "2026"
REPRT_CODE = "11012"           # 반기보고서. 기준일 기준 가장 최근 정기보고서
CHANGE_FROM = "20260701"       # 반기 기준일 다음 날부터 기준일까지 변동 공시 확인
API = "https://opendart.fss.or.kr/api"

# 평가용 다기업 목록(여러 업종). stock_code로 corp_code를 찾는다.
COMPANIES = {
    "005930": "삼성전자",
    "005380": "현대자동차",
    "010130": "고려아연",
    "008930": "한미사이언스",
    "035720": "카카오",
    "068270": "셀트리온",
    "352820": "하이브",
    "051910": "LG화학",
    # r2 추가(2026-10-27): 해시 규칙상 holdout으로 배정되는 기업 중 오너·대표 관련 보도가 많은 곳
    # 회사명은 DART 공식 회사명(corp_name)을 그대로 쓴다. 해시 배정이 회사명 문자열에 달려 있기 때문이다.
    "034730": "SK", "000880": "한화", "004990": "롯데지주", "001040": "CJ",
    "000670": "영풍", "003240": "태광산업", "000240": "한국앤컴퍼니", "004370": "농심",
    "003920": "남양유업", "003230": "삼양식품", "011780": "금호석유화학", "271560": "오리온",
    "028300": "HLB", "086520": "에코프로", "139480": "이마트", "251270": "넷마블",
    "036570": "NC", "377300": "카카오페이", "316140": "우리금융지주", "105560": "KB금융",
    "078930": "GS", "034020": "두산에너빌리티",
    "373220": "LG에너지솔루션", "032830": "삼성생명", "207940": "삼성바이오로직스",
    "005490": "POSCO홀딩스", "010950": "S-Oil", "017670": "SK텔레콤",
}


def load_key():
    """.env에서 키만 읽는다. 키 값은 어디에도 출력하지 않는다."""
    for line in (PROJECT_DIR / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DART_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("DART_API_KEY가 .env에 없습니다.")


def get_json(key, name, params):
    """OpenDART JSON API 호출. 오류 코드는 그대로 돌려준다."""
    r = requests.get(f"{API}/{name}.json", params={"crtfc_key": key, **params}, timeout=30)
    r.raise_for_status()
    time.sleep(0.3)  # 호출 간격: 서버 부담을 줄인다
    return r.json()


def corp_codes(key):
    """전체 고유번호 파일에서 대상 종목의 corp_code를 찾는다."""
    cache = RAW_DIR / "corpCode_selected.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    r = requests.get(f"{API}/corpCode.xml", params={"crtfc_key": key}, timeout=60)
    r.raise_for_status()
    xml = zipfile.ZipFile(io.BytesIO(r.content)).read("CORPCODE.xml")
    found = {}
    for el in ET.fromstring(xml).iter("list"):
        sc = (el.findtext("stock_code") or "").strip()
        if sc in COMPANIES:
            found[sc] = {"corp_code": el.findtext("corp_code"), "corp_name": el.findtext("corp_name")}
    cache.write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
    return found


def save_raw(company, api, data, kept):
    """응답 메타정보는 두고, list에는 분석 대상 항목(kept)만 남겨 저장한다."""
    data = {**data, "list": kept, "list_filter": "대주주(최대주주·1% 이상 특수관계인)·대표이사 항목만 보존"}
    path = RAW_DIR / f"{company}_{api}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path.name


def parse_date(text):
    """'2028년 03월 15일', '2028.03.15' 같은 표기를 YYYY-MM-DD로 바꾼다. 실패하면 빈칸."""
    m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", str(text or ""))
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


def clean(text):
    """공시 표 셀의 줄바꿈·연속 공백을 한 칸으로 정리한다."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def clean_name(text):
    """이름 셀 정리: '임종룡주1)' 같은 각주 표시를 떼고, '김 기 호'처럼 글자마다 띄운 한글 이름을 붙인다."""
    nm = re.sub(r"\s*주\s*\d+\)\s*$", "", clean(text))
    return nm.replace(" ", "") if re.fullmatch(r"(?:[가-힣] )+[가-힣]", nm) else nm


def to_float(text):
    try:
        return float(str(text).replace(",", ""))
    except ValueError:
        return None


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    key = load_key()
    codes = corp_codes(key)
    rows, changes = [], []
    for sc, cname in COMPANIES.items():
        if sc not in codes:
            print("corp_code 없음:", cname)
            continue
        cc = codes[sc]["corp_code"]
        base = {"corp_code": cc, "bsns_year": BSNS_YEAR, "reprt_code": REPRT_CODE}

        # 0) 반기 기준일 이후 ~ 기준일까지 대표이사·최대주주 변동 공시를 먼저 확인한다
        #    역할이 바뀌었을 수 있는 사람은 기준일 시점 지위가 불분명하므로 명부에 넣지 않는다
        # 목록 API는 한 번에 최대 100건이라 total_page까지 모두 받는다
        params = {"corp_code": cc, "bgn_de": CHANGE_FROM, "end_de": AS_OF.replace("-", ""), "page_count": 100}
        ls = get_json(key, "list", {**params, "page_no": 1})
        items = ls.get("list", []) if ls.get("status") == "000" else []
        for page in range(2, int(ls.get("total_page", 1) or 1) + 1):
            items += get_json(key, "list", {**params, "page_no": page}).get("list", [])
        kept_ls = []
        for it in items:
            nm = it.get("report_nm", "")
            # 역할 자체가 바뀌는 공시(대표이사변경·최대주주변경)와 지분율만 바뀌는 신고를 구분한다
            if re.search(r"대표이사\s*\(?.*변경", nm):
                kind = "ROLE_CHANGE_CEO"
            elif re.search(r"최대주주\s*변경", nm):
                kind = "ROLE_CHANGE_HOLDER"
            elif re.search(r"최대주주등\s*소유주식변동", nm):
                kind = "STAKE_CHANGE"
            else:
                continue
            changes.append({"company_name": cname, "kind": kind, "report_nm": clean(nm),
                            "rcept_no": it.get("rcept_no"), "rcept_dt": it.get("rcept_dt")})
            kept_ls.append(it)
        save_raw(cname, "list_since_20260701", ls, kept_ls)
        kinds = {c["kind"] for c in changes if c["company_name"] == cname}
        skip_ceo, skip_holder = "ROLE_CHANGE_CEO" in kinds, "ROLE_CHANGE_HOLDER" in kinds

        # 1) 임원 현황: 대표이사 이름·직위·임기만료일·접수번호
        ex = get_json(key, "exctvSttus", base)
        kept_ex = []
        for it in (ex.get("list", []) if ex.get("status") == "000" and not skip_ceo else []):
            # 삼성전자·현대차처럼 직위(ofcps)는 '부회장'이고 담당업무(chrg_job)에 '대표이사'가 적힌 회사가 있다
            title = clean(f"{it.get('ofcps', '')} / {it.get('chrg_job', '')}")
            # 사외·독립·비상무 이사는 대표이사가 아니다('계열사대표이사 후보추천위원' 같은 위원회 이름 때문에 잘못 잡힘)
            if (it.get("rgist_exctv_at") or "").strip() in ("사외이사", "독립이사", "기타비상무이사"):
                continue
            # '대표이사' 뒤에 '후보'가 오면 위원회 이름이다. NC처럼 담당업무를 'CEO'로만 적은 회사도 있다
            compact = title.replace(" ", "")
            if not (re.search(r"대표이사(?!후보)", compact) or re.search(r"/\s*CEO\b", title)):
                continue
            kept_ex.append(it)
            rows.append({
                "company_id": f"KRX:{sc}", "company_name": cname,
                "canonical_name": clean_name(it.get("nm")), "aliases": "",
                "role": "CEO/대표이사", "role_detail": title[:80],
                "valid_from": "",  # 공식 선임일은 이 API에 없다. 재직기간만 notes에 남긴다
                "valid_to": parse_date(it.get("tenure_end_on")),
                "as_of": parse_date(it.get("stlm_dt")) or "2026-06-30",
                "stake_ratio_end": "",
                "source_type": "opendart_exctvSttus",
                "source_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={it.get('rcept_no')}",
                "rcept_no": it.get("rcept_no", ""),
                "notes": f"등기:{it.get('rgist_exctv_at','')} 재직기간:{it.get('hffc_pd','')} 임기만료:{it.get('tenure_end_on','')}",
            })

        # 2) 최대주주 현황: 최대주주 본인과 1% 이상 특수관계인
        save_raw(cname, "exctvSttus", ex, kept_ex)
        hy = get_json(key, "hyslrSttus", base)
        kept_hy = []
        for it in (hy.get("list", []) if hy.get("status") == "000" and not skip_holder else []):
            nm = clean_name(it.get("nm"))
            relate = (it.get("relate") or "").strip()
            ratio = to_float(it.get("trmend_posesn_stock_qota_rt"))
            if nm in ("계", "합계", "") or "계" == relate:
                continue
            # '최대주주본인', '본인 및 특별관계자'(국민연금공단 등)처럼 표기가 회사마다 다르다
            compact_rel = relate.replace(" ", "")
            is_main = compact_rel in ("본인", "최대주주", "최대주주본인") or compact_rel.startswith("본인및")
            if not is_main and (ratio is None or ratio < 1.0):
                continue
            # 같은 최대주주의 우선주·특별계정 소량 행은 대상자 중복이므로 뺀다
            if "우선주" in (it.get("stock_knd") or "") or "특별계정" in nm:
                continue
            kept_hy.append(it)
            rows.append({
                "company_id": f"KRX:{sc}", "company_name": cname,
                "canonical_name": nm, "aliases": "",
                "role": "최대주주" if is_main else "주요주주(특수관계인)",
                "role_detail": f"relate={relate}; 주식종류={it.get('stock_knd','')}",
                "valid_from": "", "valid_to": "",
                "as_of": parse_date(it.get("stlm_dt")) or "2026-06-30",
                "stake_ratio_end": it.get("trmend_posesn_stock_qota_rt", ""),
                "source_type": "opendart_hyslrSttus",
                "source_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={it.get('rcept_no')}",
                "rcept_no": it.get("rcept_no", ""),
                "notes": f"기초지분율:{it.get('bsis_posesn_stock_qota_rt','')} 기말지분율:{it.get('trmend_posesn_stock_qota_rt','')}",
            })

        save_raw(cname, "hyslrSttus", hy, kept_hy)

        print(f"{cname}: 임원 {ex.get('status')} / 최대주주 {hy.get('status')} / 목록 {ls.get('status')}")

    roster = pd.DataFrame(rows)
    ch = pd.DataFrame(changes, columns=["company_name", "kind", "report_nm", "rcept_no", "rcept_dt"])
    ceo_changed = set(ch.loc[ch["kind"] == "ROLE_CHANGE_CEO", "company_name"])
    holder_changed = set(ch.loc[ch["kind"] == "ROLE_CHANGE_HOLDER", "company_name"])
    stake_changed = ch.loc[ch["kind"] == "STAKE_CHANGE"].groupby("company_name")["rcept_no"].apply(list)

    def status(row):
        # 역할 변경 공시가 있으면 그 역할 행만 기준일 재직·지위를 확정하지 않는다 → 사람 확인
        is_ceo = row["role"] == "CEO/대표이사"
        if (is_ceo and row["company_name"] in ceo_changed) or (not is_ceo and row["company_name"] in holder_changed):
            return "NEEDS_REVIEW_ROLE_CHANGE_FILED"
        # 지분 변동 신고만 있으면 역할은 유지로 보되, 지분율 수치는 보고서 기준일 값임을 표시
        if row["role"] != "CEO/대표이사" and row["company_name"] in stake_changed.index:
            return "VERIFIED_ROLE_STAKE_CHANGED_AFTER_REPORT"
        return "DART_VERIFIED_AT_REPORT_DATE"

    roster["verification_status"] = roster.apply(status, axis=1)
    roster["post_report_filings"] = roster["company_name"].map(
        lambda c: "|".join(stake_changed.get(c, [])) if c in stake_changed.index else "")
    roster["verified_by"] = "opendart_api_script"
    roster.insert(2, "person_id", [f"P{i:03d}" for i in range(1, len(roster) + 1)])
    out = PROJECT_DIR / "data" / f"person_target_roster_dart_{AS_OF.replace('-', '')}.csv"
    roster.to_csv(out, index=False, encoding="utf-8-sig")
    ch.to_csv(PROJECT_DIR / "data" / "dart_role_change_filings_20260701_20261027.csv",
                                 index=False, encoding="utf-8-sig")
    print("명부 행:", len(roster), "| 변동 공시:", len(changes), "| 저장:", out.name)


if __name__ == "__main__":
    main()
