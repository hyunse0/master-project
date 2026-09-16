# EXP-017 스키마 임베딩에 테이블별 검색 힌트 주입 (retrieval_miss 해소)

- **날짜**: 2026-09-14
- **상태**: ✅ 채택

## 배경 / 가설

[EXP-016](./exp-016-sql-validator-cte-false-positive.md) 이후에도 hard 케이스 6건 중 4건
(conv16/18/19/33)이 `retrieval_miss` — `schema_linking`의 Qdrant 벡터검색 top-5에 정답
테이블이 애초에 안 들어왔다. 실제 DB 코멘트를 조회해 원인을 확인했다:

- `poc_sslrdexrt`(정답: CT/MRI 검사 결과) 코멘트: "진단검사결과상세" — CT/MRI라는 단어가 없음
- `poc_ssnudexrt`(정답: 골스캔/PET 검사 결과) 코멘트: "핵의학**혈액검사**결과상세" — 오히려
  혈액검사로 오인하게 만듦(실제로는 영상 판독 결과)
- `poc_ssprmrsif`(병리 텍스트결과)는 위 둘과 컬럼 구성(검사번호/검사코드/결과값류)이 거의 동일
- `poc_ooodmordr`(정답: 호르몬 처방)과 `poc_ooodrmlop`(치료-수술 매핑, 오답)도 이름·코멘트가
  둘 다 "처방" 계열이라 헷갈림

세 영상검사 테이블을 구분하는 유일한 정보는 실제 데이터 값(`exam_cd`='CT001'/'MRI001' vs
'BONE001'/'PET001')인데, 스키마 코멘트 어디에도 이 값이 없어 임베딩이 원천적으로 구분할
방법이 없었다. `schema_linking`은 `prompt_fragments.yaml`의 domain_notes를 전혀 안 보는
순수 Qdrant 벡터검색이라(EXP-014/015에서 이미 확인한 배선 구조), domain_notes 텍스트를
아무리 고쳐도 이 단계엔 안 닿는다.

가설: 스키마 임베딩 텍스트 자체에 (DB comment는 건드리지 않고) 도메인팩 차원의 검색 힌트를
덧붙이면, 벡터 검색이 근접 명명의 테이블들을 구분할 수 있게 된다.

## 변경 내용

- `domains/poc_prostate/prompt_fragments.yaml`: `table_retrieval_hints` 섹션 신설 —
  `poc_sslrdexrt`/`poc_ssnudexrt`/`poc_ssprmrsif`/`poc_ooodmordr`/`poc_ooodrmlop` 5개
  테이블에 실데이터 조회로 확인한 코드값(CT001/MRI001/BONE001/PET001/ADT001/ADT002) 기준
  힌트 텍스트 추가
- `app/sql/prompt_builder.py`: `load_table_retrieval_hints()` 신규 — 위 섹션을
  `{테이블명: 힌트텍스트}` dict로 읽음(파일/키 없으면 빈 dict, 기존 도메인 영향 없음)
- `app/knowledge/schema_indexer.py`: `build_schema_index()`가 테이블별 임베딩 텍스트
  조립 시 해당 테이블 힌트가 있으면 `[검색 힌트] ...`로 덧붙이도록 수정. **DB의 실제
  COMMENT ON TABLE/COLUMN은 건드리지 않았다** — 이 프로젝트의 커넥터는 "접속 정보만 주면
  어떤 Postgres 스키마든 RAG를 구축한다"는 범용 설계라, 대상 도메인 DB가 실제로는 이
  코드베이스 소유가 아닌 경우(운영 환경의 실제 병원 스키마 등)를 가정하면 DB metadata를
  직접 고쳐 쓰는 건 재현 불가능한 임시방편이 된다. 도메인팩(`prompt_fragments.yaml`)
  차원의 보강이 이 프로젝트의 기존 패턴(`notes` 필드)과도 일관됨.
- `python app/knowledge/schema_indexer.py --domain poc_prostate`로 재색인

## 측정 방법

두 축:
1. **단위 수준(결정론적)**: retrieval_miss 4건의 질문 텍스트를 `EmbeddingEngine.embed()` +
   `qdrant_client.query_points(limit=5)`로 직접 재현 — `schema_linking` 노드가 실제로 하는
   것과 동일한 호출을 그래프 없이 격리해서, 수정 전/후 top-5에 gold 테이블이 들어오는지만
   비교(LLM 재호출 없음, 임베딩 API만 호출)
2. **골든셋 전체(aggregate)**: `eval/execution_accuracy.py --domain poc_prostate` — "변경
   전" 수치는 [EXP-016](./exp-016-sql-validator-cte-false-positive.md)의 "변경 후" 실행
   결과를 그대로 재사용(같은 골든셋·같은 코드 상태에서 다시 잴 이유가 없어 생략), "변경
   후"만 새로 1회 실행

## 결과

### 1) 단위 수준 — retrieval_miss 4건의 top-5 재현

| 질문 | gold 테이블 | 수정 전 | 수정 후 |
|---|---|---|---|
| 호르몬 치료제 처방 + 응급수술 + 병기 III↑ | `poc_ooodmordr` 포함 | ❌ miss (`poc_ooodrmlop`만 검색됨) | ✅ hit |
| 골반 CT/MRI 양성 + 병기 III↑ | `poc_sslrdexrt` 포함 | ❌ miss | ✅ hit |
| 골스캔/PET 골전이 의심 + 응급수술 | `poc_ssnudexrt` 포함 | ❌ miss | ✅ hit |
| 골스캔/PET 골전이 의심 + 병기 III↑ | `poc_ssnudexrt` 포함 | ❌ miss | ✅ hit |

4건 전부 top-5에 gold 테이블이 들어오는 것으로 전환. 회귀(원래 잘 찾던 테이블이 밀려남)는
관측되지 않음.

### 2) 골든셋 전체(aggregate)

| 지표 | 변경 전(EXP-016 이후) | 변경 후 | 차이 |
|---|---|---|---|
| Execution Accuracy (전체) | 13/38 (34.2%) | 14/38 (36.8%) | +2.6pp |
| Schema Mapping F1 | 77.9% (p=75.2%, r=87.3%) | 83.5% (p=80.3%, r=91.7%) | +5.6pp |
| Condition Summary Faithfulness | 22/31 (71.0%) | 25/33 (75.8%) | +4.8pp |

## 분석 및 결정

스키마 단계 문제(retrieval_miss)는 단위 수준에서 완전히 해결됐고, 4건 모두
`confirmed_schema`(schema_review 이후)에도 gold 테이블이 그대로 유지됨을 직접 확인했다
(review_miss로 재발하지 않음). Schema Mapping F1도 아울러 개선됐다. Execution Accuracy도
하락 없이 소폭 개선(+2.6pp)돼 [1.5절 채택 원칙](../kpi-experiment-log.md#15-채택-판단-원칙--대리지표proxy-metric-단독-개선은-채택-근거가-아니다)을
충족한다 — 채택.

다만 **retrieval_miss 4건 중 end-to-end로 정답 처리된 건 0건이다.** 4건 모두 스키마는
정확히 확정됐지만 SQL 생성에서 여전히 실패한다:
- 호르몬 처방 건: 정답은 `ordr_cd IN ('ADT001','ADT002')`인데, 생성된 SQL에 "호르몬 치료
  처방 코드가 명확하지 않으므로"라는 주석과 함께 `vald_yn='Y'` 같은 엉뚱한 대체 조건을 씀
- CT/MRI 건: 정답 컬럼은 `mark_rslt_val = 'Positive'`(표시결과값, 정규화된 판정)인데
  `exam_rslt_val ILIKE '%양성%'`(실제결과값, 원문 텍스트)을 씀 — 컬럼을 잘못 짚음
- PSA 건: 정답 코드는 `ordr_cd = 'PSA001'`인데 SQL에 "PSA 검사코드가 'PSA'라고 가정"이라는
  주석과 함께 존재하지 않는 코드를 그대로 씀

즉 이번에 만든 `table_retrieval_hints`에는 정확히 이 코드값들(ADT001/ADT002, CT001/MRI001,
mark_rslt_val vs exam_rslt_val)을 이미 적어뒀는데, **이 힌트는 `schema_indexer.py`(임베딩)
에만 배선했지 SQL 생성 프롬프트(`SqlPromptBuilder`/domain_notes)에는 연결하지 않았다** —
그래서 스키마는 정확히 찾으면서도 그 안의 "어떤 값을 써야 하는지"는 여전히 모른다.

## 새롭게 배운 것

- Retrieval 단계 개선이 Schema Mapping F1을 끌어올려도, 그게 자동으로 Execution Accuracy로
  이어지지는 않는다 — "테이블을 찾았다"와 "그 테이블의 어떤 코드값을 써야 하는지 안다"는
  서로 다른 문제이고, 후자는 이번 변경이 전혀 건드리지 못했다.
- [EXP-014](./exp-014-schema-retrieval-vs-review-bottleneck.md)/[EXP-015](./exp-015-schema-review-domain-notes-injection.md)에서
  배운 "내용이 옳아도 필요한 단계에 안 닿으면 소용없다"는 교훈이 이번엔 정반대 방향으로
  재현됐다 — 이번엔 내가 직접 그 교훈을 알면서도, 방금 작성한 코드값 힌트를 SQL 생성이
  필요로 하는 단계(domain_notes)에는 배선하지 않고 임베딩 단계에만 배선해버렸다. "값
  vocabulary는 스키마 검색과 SQL 생성 둘 다에 필요할 수 있다"는 걸 처음부터 염두에 두고
  설계했어야 했다.

## 한계

- 표본이 작다(38턴, 그중 타깃 4건). aggregate 수치는 여전히 LLM 샘플링 노이즈([EXP-016](./exp-016-sql-validator-cte-false-positive.md)에서
  확인한 대로 코드 변경 없이도 ±3턴 정도 흔들림)의 영향을 받으므로 +2.6pp라는 절대값 자체보다
  "하락하지 않았다 + 단위 수준에서 retrieval 문제가 실제로 해소됐다"는 두 사실을 근거로
  채택 판단했다.
- 이 실험은 hard 케이스의 정답률 자체를 올리지 못했다 — 다음 실험(코드값 vocabulary를
  domain_notes에도 주입해 SQL 생성이 직접 참조하게 하기)이 필요하다.
