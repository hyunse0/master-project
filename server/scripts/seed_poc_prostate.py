"""poc 스키마(poc_prostate 도메인)에 실제 쿼리 테스트용 합성 데이터를 채운다.

멱등 — 매번 poc.* 16개 테이블을 TRUNCATE하고 다시 채운다(seed_few_shot.py와 같은 방식으로
"파일이 소스 오브 트루스, DB는 파생물" 원칙을 따름). 이 도메인은 원래 rag-practice에서
마이그레이션된 실 스키마라 ddl.sql/synthetic_data.py 관례를 쓰지 않지만(plan 문서 참고),
쿼리 동작을 의미 있게 테스트하려면 기존 8명뿐인 샘플보다 더 많은 환자가 필요해 이 스크립트를
scripts/ 아래 별도로 둔다.

환자 100명(s_patno 10001~10100)의 임상 내러티브(진단 연도/병기/Gleason/수술/PSA 추이)를
생성해 4개 분석 마트 테이블(poc_prostate_patient_info/op/path/blood)에 우선 반영하고
(prompt_fragments.yaml: "분석 마트를 원천 테이블보다 우선 사용하라"), 이를 뒷받침하는
12개 원천 테이블은 NOT NULL 제약과 s_patno·날짜·코드의 논리적 일관성만 보장하는 수준으로 채운다.

사용: python scripts/seed_poc_prostate.py --domain poc_prostate
"""
import argparse
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain.loader import get_domain  # noqa: E402
from app.db.postgres_client import get_domain_connection  # noqa: E402

RNG_SEED = 20260830
NUM_PATIENTS = 100

# --------------------------------------------------------------------- 코드값 lookup --

OP_ENG_NAME = {
    "RAP001": "Robot-assisted Radical Prostatectomy",
    "RAP002": "Robotic Radical Prostatectomy (da Vinci)",
    "LAP001": "Laparoscopic Radical Prostatectomy",
    "OPN001": "Open Radical Prostatectomy",
    "SLV001": "Salvage Prostatectomy",
}
OP_METHOD = {"RAP001": "Robot", "RAP002": "Robot", "LAP001": "Lap", "OPN001": "Open", "SLV001": "Robot"}
OP_COMMENT = {
    "RAP001": "prostate robot da vinci",
    "RAP002": "prostate robot da vinci",
    "LAP001": "prostate laparoscopic",
    "OPN001": "prostate open retropubic",
    "SLV001": "prostate salvage",
}
PRIMARY_OP_CODES = ["RAP001", "RAP002", "LAP001", "OPN001"]
PRIMARY_OP_WEIGHTS = [0.35, 0.25, 0.25, 0.15]

# ordr_cd -> (한글명, 영문명, 영문약어, 행위약제구분(D=약제/E=행위), 처방테이블식별, 대분류)
ORDER_CODES = {
    "PSA001": ("전립선특이항원", "Prostate Specific Antigen", "PSA", "E", "OOSPEXAM", "LAB"),
    "PSA002": ("유리전립선특이항원", "Free PSA", "fPSA", "E", "OOSPEXAM", "LAB"),
    "TEST001": ("총테스토스테론", "Testosterone Total", "TESTO", "E", "OOSPEXAM", "LAB"),
    "ADT001": ("루프로라이드아세테이트", "Leuprolide Acetate", "LEUPRO", "D", "OOODMORD", "DRUG"),
    "ADT002": ("비칼루타마이드", "Bicalutamide", "BICAL", "D", "OOODMORD", "DRUG"),
    "CT001": ("골반전산화단층촬영", "Pelvis CT", "PEL-CT", "E", "OOSPEXAM", "RAD"),
    "MRI001": ("전립선자기공명영상", "Prostate MRI", "PROS-MRI", "E", "OOSPEXAM", "RAD"),
    "BONE001": ("전신골스캔", "Whole Body Bone Scan", "BONESCAN", "E", "OOSPEXAM", "NUC"),
    "PET001": ("PSMA PET-CT", "PSMA PET-CT", "PSMAPET", "E", "OOSPEXAM", "NUC"),
    "PATHBX01": ("전립선침생검", "Prostate Needle Biopsy", "PROSBX", "E", "OOSPEXAM", "PATH"),
}
RAD_CODES = ["CT001", "MRI001"]
NUC_CODES = ["BONE001", "PET001"]

BLOOD_LABEL = {
    "PSA001": ("PSA", "Prostate Specific Antigen"),
    "PSA002": ("freePSA", "Free PSA"),
    "TEST001": ("TEST", "Testosterone Total"),
}

JOB_CODES = ["01", "02", "03", "04", "05", "09"]

STAGE_DEF = {
    "I": {"t": ["T1c", "T2a"], "n": ["N0"], "m": ["M0"], "seer": "Local"},
    "II": {"t": ["T2b", "T2c"], "n": ["N0"], "m": ["M0"], "seer": "Local"},
    "III": {"t": ["T3a", "T3b"], "n": ["N0", "N1"], "m": ["M0"], "seer": "Regional"},
    "IV": {"t": ["T4"], "n": ["N1"], "m": ["M1", "M1a", "M1b"], "seer": "Distant"},
}
STAGE_CHOICES = ["I", "II", "III", "IV"]
STAGE_WEIGHTS = [0.22, 0.35, 0.28, 0.15]

GLEASON_BY_STAGE = {
    "I": [((3, 3), 0.75), ((3, 4), 0.25)],
    "II": [((3, 4), 0.55), ((4, 3), 0.30), ((3, 3), 0.15)],
    "III": [((4, 4), 0.35), ((4, 5), 0.25), ((4, 3), 0.20), ((3, 4), 0.20)],
    "IV": [((4, 5), 0.45), ((5, 4), 0.30), ((5, 5), 0.15), ((4, 4), 0.10)],
}
YEAR_CHOICES = list(range(2015, 2027))
YEAR_WEIGHTS = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]

TODAY = date(2026, 8, 30)


# --------------------------------------------------------------------- 헬퍼 --

def wchoice(pairs):
    items, weights = zip(*pairs)
    return random.choices(items, weights=weights, k=1)[0]


def to_date(s: str) -> date:
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))


def to_str(d: date) -> str:
    return d.strftime("%Y%m%d")


def add_days(s: str, days: int) -> str:
    return to_str(to_date(s) + timedelta(days=days))


def grade_group(g1: int, g2: int) -> int:
    return {
        (3, 3): 1,
        (3, 4): 2,
        (4, 3): 3,
        (4, 4): 4, (3, 5): 4, (5, 3): 4,
        (4, 5): 5, (5, 4): 5, (5, 5): 5,
    }.get((g1, g2), 1)


def age_decade(age: int):
    dec = (age // 10) * 10
    return str(dec // 10), f"{dec}대"


def random_date_in_year(year: int) -> str:
    start = date(year, 1, 1)
    offset = random.randint(0, 364)
    return to_str(start + timedelta(days=offset))


# --------------------------------------------------------------------- 환자 생성 --

def build_patient(idx: int) -> dict:
    s_patno = 10000 + idx
    year = random.choices(YEAR_CHOICES, weights=YEAR_WEIGHTS, k=1)[0]
    cancer_reg_no = f"PC{year}{idx:04d}"
    age = max(45, min(88, int(random.gauss(67, 8))))
    stage = random.choices(STAGE_CHOICES, weights=STAGE_WEIGHTS, k=1)[0]
    sdef = STAGE_DEF[stage]
    t_stage = random.choice(sdef["t"])
    n_stage = random.choice(sdef["n"])
    m_stage = random.choice(sdef["m"])
    g1, g2 = wchoice(GLEASON_BY_STAGE[stage])
    tertiary = "5" if (g1, g2) in ((4, 4), (4, 5), (5, 4)) and random.random() < 0.15 else None
    vist_dt = random_date_in_year(year)
    mdex_dt = add_days(vist_dt, random.randint(0, 3))
    age10_cd, age10_nm = age_decade(age)

    p = {
        "idx": idx,
        "s_patno": s_patno,
        "year": year,
        "cancer_reg_no": cancer_reg_no,
        "age": age,
        "age10_cd": age10_cd,
        "age10_nm": age10_nm,
        "stage": stage,
        "t_stage": t_stage,
        "n_stage": n_stage,
        "m_stage": m_stage,
        "seer_stage": sdef["seer"],
        "g1": g1,
        "g2": g2,
        "tertiary": tertiary,
        "grade_group": grade_group(g1, g2),
        "vist_dt": vist_dt,
        "mdex_dt": mdex_dt,
        "occur_ym": vist_dt[:6],
        "multi_cancer_yn": "Y" if random.random() < 0.06 else "N",
        "vist_sn": 1000 + idx,
        "form_drawup_no": f"FORM{year}{idx:04d}",
        "job_cd": random.choice(JOB_CODES),
        "op": None,
        "salvage_op": None,
        "rad_treat": "N",
        "tb_chem": "N",
        "hormone": False,
        "remote_metas": "Y" if stage == "IV" else "N",
        "remote_metas_part": None,
        "remote_metas_type": None,
        "path_g1": None,
        "path_g2": None,
        "death_dt": None,
        "op_schd_seq": 0,
    }

    if stage == "IV":
        p["remote_metas_part"] = random.choice(["Bone", "Lung", "Liver", "Lymph node"])
        p["remote_metas_type"] = "Distant metastasis"

    # ---- 치료 방침: 병기에 따라 수술/방사선/항암/호르몬 조합 ----
    op_roll = random.random()
    if stage == "I":
        has_op = op_roll < 0.90
        p["rad_treat"] = "N" if has_op or random.random() < 0.7 else "Y"
    elif stage == "II":
        has_op = op_roll < 0.88
        p["rad_treat"] = "Y" if not has_op else ("Y" if random.random() < 0.1 else "N")
    elif stage == "III":
        has_op = op_roll < 0.55
        p["rad_treat"] = "Y" if (not has_op) or random.random() < 0.4 else "N"
        p["hormone"] = random.random() < 0.5
    else:  # IV
        has_op = op_roll < 0.05
        p["tb_chem"] = "Y" if random.random() < 0.45 else "N"
        p["rad_treat"] = "Y" if random.random() < 0.35 else "N"
        p["hormone"] = random.random() < 0.85

    if has_op:
        op_code = random.choices(PRIMARY_OP_CODES, weights=PRIMARY_OP_WEIGHTS, k=1)[0]
        op_dt = add_days(vist_dt, random.randint(30, 90))
        p["op_schd_seq"] += 1
        p["op"] = {
            "op_schd_no": f"OP{year}{idx:04d}",
            "op_dt": op_dt,
            "inhosp_op_cd": op_code,
            "op_knd_cd": "1",
            "emrcy_op_yn": "Y" if random.random() < 0.04 else "N",
        }
        # 병리(수술검체) 등급: 생검보다 한 단계 상향될 수 있음
        if random.random() < 0.3 and (g1, g2) != (5, 5):
            p["path_g1"], p["path_g2"] = min(g1 + 1, 5), g2
        else:
            p["path_g1"], p["path_g2"] = g1, g2

        # 재발로 인한 구제수술(salvage), 일부 환자에서 6~24개월 뒤
        if random.random() < 0.08:
            salvage_dt = add_days(op_dt, random.randint(180, 720))
            if to_date(salvage_dt) <= TODAY:
                p["salvage_op"] = {
                    "op_schd_no": f"OP{salvage_dt[:4]}{idx:04d}S",
                    "op_dt": salvage_dt,
                    "inhosp_op_cd": "SLV001",
                    "op_knd_cd": "2",
                    "emrcy_op_yn": "N",
                }

    # 사망 여부: 진단 후 시간 경과 + 병기에 따라 일부 사망 처리
    years_since_dx = (TODAY - to_date(vist_dt)).days / 365.25
    death_prob = {"I": 0.01, "II": 0.03, "III": 0.08, "IV": 0.35}[stage] * min(years_since_dx / 5, 1.5)
    if random.random() < death_prob:
        death_offset = random.randint(200, max(201, int(years_since_dx * 365) - 30))
        p["death_dt"] = add_days(vist_dt, death_offset)

    return p


def build_blood_tests(p: dict, exam_counter: list) -> list:
    """환자 1명의 PSA/테스토스테론 검사 이력을 만든다."""
    rows = []
    stage = p["stage"]
    vist_dt = p["vist_dt"]

    def baseline_psa():
        if stage == "I":
            return round(random.uniform(3.0, 9.9), 2)
        if stage == "II":
            return round(random.uniform(6.0, 20.0), 2)
        if stage == "III":
            return round(random.uniform(12.0, 55.0), 2)
        return round(random.uniform(40.0, 500.0), 2)

    rn = 1

    def add_test(dt, ordr_cd, val):
        nonlocal rn
        exam_counter[0] += 1
        rows.append({
            "rcep_dt": dt,
            "s_patno": p["s_patno"],
            "ordr_direct_dt": dt,
            "ordr_cd": ordr_cd,
            "exam_cd": f"E{exam_counter[0]:06d}",
            "exam_no": f"EX{dt[:4]}{exam_counter[0]:05d}",
            "finsh_dt": add_days(dt, 1),
            "mark_rslt_val": str(val),
            "erp_dtl_cd": BLOOD_LABEL[ordr_cd][0],
            "dtl_cd_nm": BLOOD_LABEL[ordr_cd][1],
            "rn": rn,
        })
        rn += 1

    # 진단 시점 baseline PSA (+ 30% 확률로 free PSA 동시 시행)
    add_test(vist_dt, "PSA001", baseline_psa())
    if random.random() < 0.3:
        add_test(vist_dt, "PSA002", round(random.uniform(0.5, 3.0), 2))
    if stage == "IV" and random.random() < 0.4:
        add_test(vist_dt, "TEST001", round(random.uniform(200, 600), 1))

    # 수술 후 추적 PSA
    if p["op"]:
        op_dt = p["op"]["op_dt"]
        nadir_dt = add_days(op_dt, random.randint(60, 100))
        if to_date(nadir_dt) <= TODAY:
            add_test(nadir_dt, "PSA001", round(random.uniform(0.01, 0.05), 3))
            follow_dt = add_days(nadir_dt, random.randint(240, 300))
            if to_date(follow_dt) <= TODAY:
                if random.random() < 0.15:
                    add_test(follow_dt, "PSA001", round(random.uniform(0.2, 3.0), 2))  # 생화학적 재발
                else:
                    add_test(follow_dt, "PSA001", round(random.uniform(0.01, 0.08), 3))

    # 호르몬 치료 중인 환자는 6개월 간격 PSA + 테스토스테론 억제 확인
    if p["hormone"]:
        for k in range(1, random.randint(2, 4)):
            follow_dt = add_days(vist_dt, k * 180)
            if to_date(follow_dt) > TODAY:
                break
            add_test(follow_dt, "PSA001", round(baseline_psa() * (0.5 ** k), 2))
            if random.random() < 0.5:
                add_test(follow_dt, "TEST001", round(random.uniform(5, 40), 1))

    return rows


def build_imaging(p: dict, seq: list) -> list:
    """병기 workup용 영상/핵의학 오더 + 결과 (일부 환자만)."""
    stage = p["stage"]
    prob = {"I": 0.35, "II": 0.5, "III": 0.75, "IV": 0.9}[stage]
    if random.random() > prob:
        return []

    n_studies = 1 if stage in ("I", "II") else random.choice([1, 2])
    studies = []
    pool = RAD_CODES if stage in ("I", "II") else RAD_CODES + NUC_CODES
    chosen = random.sample(pool, k=min(n_studies, len(pool)))
    for exam_cd in chosen:
        seq[0] += 1
        order_dt = add_days(p["vist_dt"], random.randint(-5, 10))
        studies.append({"exam_cd": exam_cd, "order_dt": order_dt, "seq": seq[0]})
    return studies


# --------------------------------------------------------------------- 메인 --

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", default="poc_prostate")
    parser.add_argument("--patients", type=int, default=NUM_PATIENTS)
    args = parser.parse_args()

    random.seed(RNG_SEED)
    domain = get_domain(args.domain)

    patients = [build_patient(i) for i in range(1, args.patients + 1)]

    exam_counter = [0]
    blood_rows: list[dict] = []
    for p in patients:
        blood_rows.extend(build_blood_tests(p, exam_counter))

    imaging_seq = [0]
    imaging_by_patient: dict[int, list[dict]] = {}
    for p in patients:
        imaging_by_patient[p["s_patno"]] = build_imaging(p, imaging_seq)

    conn = get_domain_connection(domain.connection)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            truncate_all(cur)
            n1 = insert_patient_info(cur, patients)
            n2 = insert_path(cur, patients)
            n3 = insert_op(cur, patients)
            n4 = insert_blood(cur, blood_rows)
            n5 = insert_msmamcamn(cur, patients)
            n6 = insert_msmacopcd(cur)
            n7 = insert_oootmodcd(cur)
            n8 = insert_opsmmsurg_opcd_ooodrmlop(cur, patients)
            n9 = insert_ooodmordr(cur, patients)
            n10 = insert_ssspmordr_and_results(cur, patients, imaging_by_patient)
            n11 = insert_fmfcrdrup(cur, patients)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[{args.domain}] 환자 {len(patients)}명 기준 시드 완료:")
    print(f"  poc_prostate_patient_info: {n1}")
    print(f"  poc_prostate_path:         {n2}")
    print(f"  poc_prostate_op:           {n3}")
    print(f"  poc_prostate_blood:        {n4}")
    print(f"  poc_msmamcamn:             {n5}")
    print(f"  poc_msmacopcd:             {n6}")
    print(f"  poc_oootmodcd:             {n7}")
    print(f"  poc_opsmmsurg/opcd/ooodrmlop(합계): {n8}")
    print(f"  poc_ooodmordr:             {n9}")
    print(f"  poc_ssspmordr+sslrdexrt+ssnudexrt+ssprmrsif(합계): {n10}")
    print(f"  poc_fmfcrdrup:             {n11}")


def truncate_all(cur) -> None:
    tables = [
        "poc_fmfcrdrup", "poc_msmacopcd", "poc_msmamcamn", "poc_ooodmordr",
        "poc_ooodrmlop", "poc_oootmodcd", "poc_opsmmopcd", "poc_opsmmsurg",
        "poc_prostate_blood", "poc_prostate_op", "poc_prostate_path",
        "poc_prostate_patient_info", "poc_sslrdexrt", "poc_ssnudexrt",
        "poc_ssprmrsif", "poc_ssspmordr",
    ]
    cur.execute("TRUNCATE TABLE " + ", ".join(f"poc.{t}" for t in tables))


def insert_patient_info(cur, patients: list[dict]) -> int:
    cols = [
        "cancer_reg_no", "crcn_cd", "mddp_cd", "prmr_organ_cd", "mrph_diag_cd", "std_diag_cd",
        "s_patno", "vist_sn", "occur_ym", "vist_dt", "mdex_dt", "base_dt", "age",
        "age_10_sect_cd", "age_10_sect_nm", "multi_cancer_yn", "first_day_amc", "target_rag",
        "remote_metas", "remote_metas_part", "remote_metas_type",
        "seer_stage", "dis_stage", "dis_t_stage", "dis_n_stage", "dis_m_stage",
        "clinic_stage", "clinic_t_stage", "clinic_n_stage", "clinic_m_stage",
        "op_dt", "op_nm", "op_type", "op_mthd", "rad_treat", "tb_chem",
        "path_grade", "path_gs_score1", "path_gs_score2",
        "biopsy_grade", "biopsy_gs_score1", "biopsy_gs_score2",
    ]
    rows = []
    for p in patients:
        op = p["op"]
        rows.append((
            p["cancer_reg_no"], "C61", "URO", "C619", "8140/3", "C61",
            p["s_patno"], p["vist_sn"], p["occur_ym"], p["vist_dt"], p["mdex_dt"], p["vist_dt"], p["age"],
            p["age10_cd"], p["age10_nm"], p["multi_cancer_yn"], add_days(p["vist_dt"], -random.randint(30, 500)), "Y",
            p["remote_metas"], p["remote_metas_part"], p["remote_metas_type"],
            p["seer_stage"], p["stage"], p["t_stage"], p["n_stage"], p["m_stage"],
            p["stage"], p["t_stage"], p["n_stage"], p["m_stage"],
            op["op_dt"] if op else None, OP_ENG_NAME[op["inhosp_op_cd"]] if op else None,
            "RP" if op else None, OP_METHOD[op["inhosp_op_cd"]] if op else None,
            p["rad_treat"], p["tb_chem"],
            "Adenocarcinoma" if op else None, p["path_g1"] if op else None, p["path_g2"] if op else None,
            "Adenocarcinoma", p["g1"], p["g2"],
        ))
    execute_insert(cur, "poc.poc_prostate_patient_info", cols, rows)
    return len(rows)


def insert_path(cur, patients: list[dict]) -> int:
    cols = [
        "s_patno", "vist_sn", "ordr_no", "ordr_direct_dt", "rslt_cnfm_dt",
        "gleason", "t_gleason", "tertiary", "score", "score1", "score2", "grade_group",
    ]
    rows = []
    for p in patients:
        ordr_no = f"PATH{p['year']}{p['idx']:04d}"
        rslt_cnfm_dt = add_days(p["vist_dt"], random.randint(10, 15))
        rows.append((
            p["s_patno"], p["vist_sn"], ordr_no, p["vist_dt"], rslt_cnfm_dt,
            str(p["g1"]), str(p["g2"]), p["tertiary"], str(p["g1"] + p["g2"]),
            str(p["g1"]), str(p["g2"]), str(p["grade_group"]),
        ))
    execute_insert(cur, "poc.poc_prostate_path", cols, rows)
    return len(rows)


def _op_rows(patients: list[dict]):
    for p in patients:
        for op in filter(None, [p["op"], p["salvage_op"]]):
            yield p, op


def insert_op(cur, patients: list[dict]) -> int:
    cols = [
        "op_schd_no", "mnop_schd_no", "op_knd_cd", "emrcy_op_yn", "emrcy_op_rsn_cd",
        "op_dt", "s_patno", "orc_vist_sn", "bfor_op_dt", "next_op_dt", "opdp_cd",
        "inhosp_op_cd", "inhosp_op_eng_nm", "op_cmnt",
    ]
    rows = []
    for p, op in _op_rows(patients):
        is_salvage = op is p["salvage_op"]
        bfor = p["op"]["op_dt"] if (is_salvage and p["op"]) else None
        nxt = p["salvage_op"]["op_dt"] if (not is_salvage and p["salvage_op"]) else None
        rows.append((
            op["op_schd_no"], op["op_schd_no"], op["op_knd_cd"], op["emrcy_op_yn"],
            "N" if op["emrcy_op_yn"] == "N" else "ACUTE_URINARY_RETENTION",
            op["op_dt"], p["s_patno"], 2000 + p["idx"], bfor, nxt, "URO",
            op["inhosp_op_cd"], OP_ENG_NAME[op["inhosp_op_cd"]], OP_COMMENT[op["inhosp_op_cd"]],
        ))
    execute_insert(cur, "poc.poc_prostate_op", cols, rows)
    return len(rows)


def insert_blood(cur, blood_rows: list[dict]) -> int:
    cols = [
        "rcep_dt", "s_patno", "ordr_direct_dt", "ordr_cd", "exam_cd", "exam_no",
        "finsh_dt", "mark_rslt_val", "erp_dtl_cd", "dtl_cd_nm", "rn",
    ]
    rows = [tuple(r[c] for c in cols) for r in blood_rows]
    execute_insert(cur, "poc.poc_prostate_blood", cols, rows)
    return len(rows)


def insert_msmamcamn(cur, patients: list[dict]) -> int:
    cols = [
        "cancer_reg_no", "vald_yn", "form_drawup_no", "s_patno", "crcn_cd", "prmr_organ_cd",
        "mrph_diag_cd", "pmh_yn", "multi_cancer_yn", "ilwy_yn", "fore_yn", "age", "job_cd",
        "vist_div_cd", "vist_dt", "dchrg_dt", "cancer_reg_dt", "vist_sn", "mddp_cd", "mdex_dt",
        "finl_vist_dt", "occur_ym", "cancer_mchs_typ_cd", "std_diag_cd", "cancer_reg_stat_cd",
        "usr_empno", "admis_dt", "wardtrns_yn", "deptr_yn", "tdy_mdex_yn", "priod_by_fvist_div_cd",
        "frst_rcep_dt", "frst_mddp_cd", "frst_ward_cd", "tdy_aad_yn", "stay_days", "mdfe_occur_cd",
        "vist_confm_yn", "ward_cd", "std_diag_st_dt", "death_dt", "dtcs_std_diag_cd",
        "survival_priod_year", "survival_priod_mon", "survival_priod_day",
    ]
    rows = []
    for p in patients:
        admitted = p["op"] is not None
        stay_days = random.randint(3, 9) if admitted else 0
        admis_dt = add_days(p["op"]["op_dt"], -1) if admitted else None
        dchrg_dt = add_days(p["op"]["op_dt"], stay_days - 1) if admitted else None
        end_dt = p["death_dt"] or TODAY.strftime("%Y%m%d")
        days_survived = (to_date(end_dt) - to_date(p["vist_dt"])).days
        rows.append((
            p["cancer_reg_no"], "Y", p["form_drawup_no"], p["s_patno"], "C61", "C619",
            "8140/3", "N", p["multi_cancer_yn"], "N", "N", p["age"], p["job_cd"],
            "2" if admitted else "1", p["vist_dt"], dchrg_dt, add_days(p["vist_dt"], 20), p["vist_sn"], "URO", p["mdex_dt"],
            p["death_dt"] or add_days(p["vist_dt"], random.randint(30, 365)), p["occur_ym"], "1", "C61",
            "CONFIRMED" if not p["death_dt"] else "DECEASED",
            f"EMP{1000 + (p['idx'] % 30):04d}", admis_dt, "N", "N", "Y", "1",
            p["vist_dt"], "URO", "7W" if admitted else "OPD", "N", stay_days, "1",
            "Y", "7W" if admitted else None, p["vist_dt"], p["death_dt"], "C61" if p["death_dt"] else None,
            str(days_survived // 365), str((days_survived % 365) // 30), str(days_survived % 30),
        ))
    execute_insert(cur, "poc.poc_msmamcamn", cols, rows)
    return len(rows)


def insert_msmacopcd(cur) -> int:
    cols = [
        "inhosp_op_cd", "use_yn", "inhosp_op_eng_nm", "shrtg_op_nm", "ordr_posbl_yn",
        "inhosp_op_synn_cd", "inhosp_op_st_dt", "inhosp_op_end_dt",
    ]
    rows = [
        (code, "Y", name, name.split()[0][:10].upper(), "Y", None, "20100101", "20991231")
        for code, name in OP_ENG_NAME.items()
    ]
    execute_insert(cur, "poc.poc_msmacopcd", cols, rows)
    return len(rows)


def insert_oootmodcd(cur) -> int:
    cols = [
        "ordr_cd", "hlin_phrm_div_cd", "ordr_kor_nm", "ordr_eng_nm", "ordr_eng_abrv_nm",
        "srwr_val", "ordr_tbl_dstg_cd", "apply_st_dt", "apply_end_dt",
        "bfor_ordr_cd", "hlin_typ_cd", "hlin_lclas_cd", "hlin_mclas_cd", "hlin_sclas_cd",
    ]
    rows = []
    for code, (kor, eng, abrv, phrm, tbl, lclas) in ORDER_CODES.items():
        rows.append((code, phrm, kor, eng, abrv, abrv, tbl, "20100101", "20991231", None, phrm, lclas, lclas, lclas))
    execute_insert(cur, "poc.poc_oootmodcd", cols, rows)
    return len(rows)


def insert_opsmmsurg_opcd_ooodrmlop(cur, patients: list[dict]) -> int:
    surg_cols = [
        "op_schd_no", "s_patno", "op_dt", "op_knd_cd", "mnop_schd_no", "vald_op_yn",
        "op_schd_cnfm_yn", "op_schd_cnfm_dtm", "emrcy_op_yn", "emrcy_op_rsn_cd",
        "expect_orc_vist_sn", "orc_vist_sn", "roset_cd", "oprm_cd", "opdp_cd",
        "op_st_dtm", "op_end_dtm", "bfor_op_dt", "next_op_dt",
    ]
    opcd_cols = ["op_schd_no", "op_boa_op_nm_sn", "op_boa_div_cd", "inhosp_op_cd", "mnop_yn", "op_cmnt", "bfor_inhosp_op_cd"]
    ooodrmlop_cols = [
        "ordr_no", "vald_yn", "s_patno", "vist_sn", "ordr_direct_dt",
        "ordr_tbl_dstg_cd", "ordr_entr_progrm_cd", "op_schd_no", "op_dt", "inhosp_op_cd",
    ]
    surg_rows, opcd_rows, ordr_rows = [], [], []
    for p, op in _op_rows(patients):
        is_salvage = op is p["salvage_op"]
        bfor = p["op"]["op_dt"] if (is_salvage and p["op"]) else None
        nxt = p["salvage_op"]["op_dt"] if (not is_salvage and p["salvage_op"]) else None
        op_dt = op["op_dt"]
        cnfm_dtm = datetime.combine(to_date(op_dt) - timedelta(days=7), datetime.min.time()).replace(hour=10)
        st_dtm = datetime.combine(to_date(op_dt), datetime.min.time()).replace(hour=9)
        end_dtm = st_dtm + timedelta(hours=random.randint(2, 5))
        surg_rows.append((
            op["op_schd_no"], p["s_patno"], op_dt, op["op_knd_cd"], op["op_schd_no"], "Y",
            "Y", cnfm_dtm, op["emrcy_op_yn"], "N" if op["emrcy_op_yn"] == "N" else "ACUTE_URINARY_RETENTION",
            2000 + p["idx"], 2000 + p["idx"], "R1", f"OR{(p['idx'] % 5) + 1}", "URO",
            st_dtm, end_dtm, bfor, nxt,
        ))
        opcd_rows.append((op["op_schd_no"], 1, "1", op["inhosp_op_cd"], "Y", OP_COMMENT[op["inhosp_op_cd"]], None))
        ordr_rows.append((
            f"SO{op['op_schd_no']}", "Y", p["s_patno"], p["vist_sn"], op_dt,
            "OP", "OR", op["op_schd_no"], op_dt, op["inhosp_op_cd"],
        ))
    execute_insert(cur, "poc.poc_opsmmsurg", surg_cols, surg_rows)
    execute_insert(cur, "poc.poc_opsmmopcd", opcd_cols, opcd_rows)
    execute_insert(cur, "poc.poc_ooodrmlop", ooodrmlop_cols, ordr_rows)
    return len(surg_rows) + len(opcd_rows) + len(ordr_rows)


def insert_ooodmordr(cur, patients: list[dict]) -> int:
    cols = [
        "ordr_no", "ordr_tbl_dstg_cd", "s_patno", "ordr_direct_dt", "ordr_titl_cd",
        "vist_sn", "mdex_div_cd", "mddp_cd", "vald_yn", "ordr_cancel_cd",
        "ordr_mddp_cd", "ordr_cd", "artcl_cd", "ordr_cnt", "ordr_days",
    ]
    rows = []
    for p in patients:
        if not p["hormone"]:
            continue
        n_orders = random.randint(1, 3)
        for k in range(n_orders):
            direct_dt = add_days(p["vist_dt"], k * 90 + random.randint(0, 10))
            if to_date(direct_dt) > TODAY:
                break
            drug_cd = random.choice(["ADT001", "ADT002"])
            rows.append((
                f"RX{p['year']}{p['idx']:04d}{k}", "OPD", p["s_patno"], direct_dt, "DRUG",
                p["vist_sn"], "O", "URO", "Y", "N",
                "URO", drug_cd, f"ART{drug_cd}", 1, 90 if drug_cd == "ADT001" else 28,
            ))
    execute_insert(cur, "poc.poc_ooodmordr", cols, rows)
    return len(rows)


def insert_ssspmordr_and_results(cur, patients: list[dict], imaging_by_patient: dict) -> int:
    ordr_cols = [
        "ordr_no", "exam_sn", "s_patno", "ordr_direct_dt", "vist_sn", "mdex_div_cd", "mddp_cd",
        "pat_loc_cd", "exam_resv_dt", "ordr_cd", "ordr_cnt", "exam_cd", "hope_dt",
        "ordr_cancel_cd", "vald_yn", "ordr_progrs_stat_cd", "exam_no", "spcn_no", "ordr_clsf_cd",
    ]
    sslrd_cols = [
        "exam_no", "exam_cd", "rslt_sn", "ordr_cd", "s_patno", "exam_rslt_val", "mark_rslt_val",
        "dgi_rcep_dt", "spcn_no", "ordr_direct_dt", "rslt_rport_dt",
    ]
    ssnud_cols = [
        "exam_no", "exam_cd", "rslt_sn", "ordr_cd", "spcn_no", "s_patno", "exam_rslt_stat_cd",
        "rcep_dt", "finsh_dt", "actul_rslt_val", "mark_rslt_val", "ordr_no", "ordr_direct_dt",
    ]
    ssprm_cols = [
        "exam_rslt_no", "org_exam_no", "rslt_progrs_stat_cd", "rslt_frst_entr_dt",
        "rslt_frst_cnfm_dt", "rslt_cnfm_dt", "confm_dt", "exam_rslt_text_cnte",
    ]
    ordr_rows, sslrd_rows, ssnud_rows, ssprm_rows = [], [], [], []

    for p in patients:
        # 병리(생검) 검사 오더 — poc_prostate_path와 ordr_no 공유
        path_ordr_no = f"PATH{p['year']}{p['idx']:04d}"
        ordr_rows.append((
            path_ordr_no, 1, p["s_patno"], p["vist_dt"], p["vist_sn"], "O", "URO",
            "OPD", p["vist_dt"], "PATHBX01", 1, "PATHBX", None,
            "N", "Y", "COMPLETE", None, f"SP{p['s_patno']}", "PATH",
        ))

        for study in imaging_by_patient.get(p["s_patno"], []):
            exam_cd = study["exam_cd"]
            order_dt = study["order_dt"]
            is_rad = exam_cd in RAD_CODES
            exam_no = f"{'RAD' if is_rad else 'NUC'}{order_dt[:4]}{study['seq']:05d}"
            spcn_no = f"SP{study['seq']:06d}"
            ordr_rows.append((
                f"IMG{order_dt[:4]}{study['seq']:05d}", 1, p["s_patno"], order_dt, p["vist_sn"], "O", "URO",
                "OPD", order_dt, exam_cd, 1, "RAD" if is_rad else "NUC", None,
                "N", "Y", "COMPLETE", exam_no, spcn_no, "RAD" if is_rad else "NUC",
            ))
            report_dt = add_days(order_dt, random.randint(1, 3))
            if is_rad:
                finding = "No evidence of extraprostatic extension." if p["stage"] in ("I", "II") \
                    else "Findings suggestive of extracapsular extension."
                sslrd_rows.append((
                    exam_no, exam_cd, 1, exam_cd, p["s_patno"], finding,
                    "Negative" if p["stage"] in ("I", "II") else "Positive",
                    order_dt, spcn_no, order_dt, report_dt,
                ))
            else:
                positive = p["stage"] == "IV" and random.random() < 0.6
                val = round(random.uniform(3.0, 9.0), 1) if positive else round(random.uniform(0.5, 2.5), 1)
                ssnud_rows.append((
                    exam_no, exam_cd, 1, exam_cd, spcn_no, p["s_patno"], "F",
                    order_dt, add_days(order_dt, 1), val,
                    "Positive" if positive else "Negative",
                    f"IMG{order_dt[:4]}{study['seq']:05d}", order_dt,
                ))
            ssprm_rows.append((
                f"RPT{exam_no}", exam_no, "CONFIRMED", report_dt, report_dt, report_dt, report_dt,
                (finding if is_rad else ("Positive uptake suspicious for osseous metastasis."
                                          if val >= 3.0 else "No abnormal uptake to suggest metastasis.")),
            ))

    execute_insert(cur, "poc.poc_ssspmordr", ordr_cols, ordr_rows)
    execute_insert(cur, "poc.poc_sslrdexrt", sslrd_cols, sslrd_rows)
    execute_insert(cur, "poc.poc_ssnudexrt", ssnud_cols, ssnud_rows)
    execute_insert(cur, "poc.poc_ssprmrsif", ssprm_cols, ssprm_rows)
    return len(ordr_rows) + len(sslrd_rows) + len(ssnud_rows) + len(ssprm_rows)


def insert_fmfcrdrup(cur, patients: list[dict]) -> int:
    cols = [
        "form_drawup_no", "form_drawup_clau_sn", "form_drawup_clau_hist_sn", "form_sht_cd",
        "form_clau_sn", "form_clau_typ_cd", "form_drawup_clau_typ_cd", "form_drawup_stat_cd",
        "form_drawup_hist_sn", "form_cd", "form_cd_sn", "s_patno", "pat_vist_sn", "rec_dt",
        "form_in_incl_img_drawup_yn",
    ]
    rows = []
    for p in patients:
        rows.append((
            p["form_drawup_no"], 1, 1, "SHT01",
            1, "TEXT", "TEXT", "CONFIRMED",
            1, "CANCER_REG", 1, p["s_patno"], p["vist_sn"], p["vist_dt"],
            "N",
        ))
    execute_insert(cur, "poc.poc_fmfcrdrup", cols, rows)
    return len(rows)


def execute_insert(cur, table: str, cols: list[str], rows: list[tuple]) -> None:
    if not rows:
        return
    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
    cur.executemany(sql, rows)


if __name__ == "__main__":
    main()
