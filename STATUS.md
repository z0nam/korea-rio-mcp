# korea-rio-mcp 진행 상황 (2026-07-21)

지역산업연관분석(RIO)을 **임의 지역에 재사용 가능한 cross-platform MCP 서버**로 일반화하는 프로젝트.
26p17(서귀포 축제 경제효과) 제주 전용 코드에서 출발 → **전국 17개 시·도 × 3지표**로 확장 완료.

> 이 문서는 새 세션이 맥락을 바로 잡도록 정리한 핸드오프. 원하면 `CLAUDE.md`로 복사하면 세션 시작 시 자동 로드됨.

---

## 1. 무엇을 만들었나

cross-platform 요구(codex·gemini·claude) 때문에 Claude 전용 skill이 아니라 **MCP 서버(stdio)**로 구현.
세 가지 목적:
1. **베이스표 입수** — 한국은행 지역 IO 유발계수 입수·계수 추출
2. **효과 산출** — 임의 지역의 경제이벤트 → 생산·부가가치·취업 유발효과 (도내/도외 분리)
3. **표준 문서화** — interim(생산유발만)/final(3지표) 마크다운 표

판단이 많은 단계(예산항목→부문 매핑, 설문 처리)는 결정론적 도구 대신 **prompt**로 LLM 계층에 위임.

---

## 2. 현재 상태: 전국 17개 시·도 × 3지표 완성

| 지표 | 17개 시·도 | 출처 |
|---|---|---|
| 생산유발 | ✅ | KOSIS 지역표 통합중분류 생산유발계수 |
| 부가가치유발 | ✅ | KOSIS 지역표 통합중분류 부가가치유발계수 |
| 취업유발 | ✅ | 2020 지역 부속표_고용표 통합중분류 (취업유발계수표 시트) |

- 17개 시·도: 서울·인천·경기·대전·세종·충북·충남·광주·전북·전남·대구·경북·부산·울산·경남·강원·제주
- 분류: 통합중분류 **83부문** (26p17과 동일, 부문코드 01~83)
- 단위: 생산·부가가치 = 원/원, 취업 = 명/10억원
- git: `0d6b575`(초기) → `1a865f8`(17지역 생산·부가가치) → `9bbade9`(취업 추가, 3지표 완성)
- 테스트: **pytest 16 passed** (골든 8 + 프로파일/방문객그룹 8)

### 2026-07-21 확장: 소비 프로파일 + 방문객 그룹 (제주포럼 MICE 트랙)

제21회 제주포럼(2026.6, 참가 6,062명 = 내국인 5,371/외국인 691) 파급효과 분석을 위해
참가자 소비 채널을 일반화. 축제(26p17) 경로는 골든 테스트로 무손상 보증.

- **소비 프로파일**: 단가표를 `data/reference/profiles/<name>/`(unit_cost.csv +
  industry_mapping.csv + meta.json + SOURCE.md)로 재편. 기간 컬럼 임의(월별 또는
  `annual` 단일) — meta의 `default_weight`가 기본 가중. 번들 7종:
  | 프로파일 | 대상 | 출처 |
  |---|---|---|
  | `jeju_domestic_leisure` | 내국인 레저(축제) | 국민여행조사(기존 26p17) |
  | `jeju_domestic_visitor` | 내국인 개별여행객(전 목적) | **2025 제주 방문관광객 실태조사** 그림 3-19 (1차 출처) |
  | `jeju_domestic_business` | 내국인 비즈니스/교육 목적 | 동일 표 3-56 (n=319) — forum_mice 기본 |
  | `jeju_foreign_visitor` | 외국인 개별여행객(전 목적) | 동일 그림 4-21 (USD×1,421.9원) |
  | `jeju_foreign_business` | 외국인 비즈니스/교육 목적 | 동일 표 4-63 (n=86, 소표본 주의) |
  | `jeju_domestic_mice_kto2016` | 내국인 컨벤션(제주) | KTO 2016 MICE 파급효과 부록-3 (민감도) |
  | `jeju_foreign_mice_kto2016` | 외국인 컨벤션(제주) | 동일 (민감도) |
  실태조사 원본 PDF(2024·2025 분석편/통계편)는 과제폴더
  `99.Reference/외부문헌/02_제주도_제주관광공사/`에 보관. 2025 외래관광객조사
  마이크로데이터(제주 방문 n=1,214 재집계)는 `30.data/20260721_외래관광객조사_원자료_제주재집계.md` 참조.
- **visitor_groups**: `effects.visitor_group_effects()` / `rio_compute_event`의
  `event_spec.visitor_groups` — 그룹(내/외국인)별로 다른 프로파일·파라미터를 태워 합산,
  그룹별 요약(`participant_by_group`) 반환.
- **event_type 프리셋**: `defaults.EVENT_TYPE_PRESETS` — `festival`(기존 디폴트와 동일),
  `forum_mice`(purpose_weight 1.0, 현장소비 채널 기본 OFF: 주최측 예산의 케이터링과
  이중계상 방지, per_capita_won 명시 시에만 ON).
- **MCP 도구 추가**: `rio_list_profiles`.
- **주의(분석자 판단 사항)**: 초청 인사의 숙박·항공은 예산 채널(초청경비)에 이미 있음 →
  해당 인원의 체류소비 숙박 항목 이중계상 보정 필요. 도민 비중·연인원→고유인원 환산은
  엔진 밖(호출부)에서 n에 반영. 외국인 visitor 단가는 평균 체류 6.72일 전제의 여행 1회당
  값이라 2박3일 행사엔 과대 가능(SOURCE.md 참조).
- macOS NFD 파일명 이슈 픽스: `cache.list_available()`가 NFC 정규화해 반환.

---

## 3. 핵심 방법론: 다지역 행블록 합산

한국은행 지역 유발계수표는 **17지역×83부문 행 × 17지역×83부문 열 + 전국 합계행**의 다지역 행렬(1419행). 사전계산된 지역 소계행이 없으므로, 임의 지역 R의 유발계수를 다음으로 산출:

- **도내 효과** = R의 자기 행블록(83행) 합 (열 = R의 부문 j)
- **전국** = 569/맨끝 전국 전지역열합계 행
- **도외 누출** = 전국 − 도내

`engine/multiregional.py`가 이 추출을 담당. 생산·부가가치·취업 세 파일 모두 동일 레이아웃이라 같은 알고리즘.

### 검증 (제주 골든)
- 제주 행블록 추출 = 기존 26p17 제주 계수와 **diff ~2e-16**(생산·부가가치), **~2e-15**(취업) → 완전 일치
- P09 정책지출: 생산유발 도내 **350.3085** 백만원, 취업 **2.3885** 명 정확 재현
- **중요:** BOK는 지역별 **고유** 취업계수 사용. "전국 취업계수 × 지역 역행렬" 근사는 오차 13까지 나서 **폐기**(직접 시험 후 기각). 진짜 지역 고용표라야 맞음.

---

## 4. 데이터 출처 (재현용)

원본 xlsx는 용량이 커서(각 27~31MB) repo에 넣지 않음. **26p17 프로젝트에 보관**, 추출된 작은 CSV(17개, 총 ~280KB)만 번들.

| 자료 | 경로 | 입수 |
|---|---|---|
| 생산유발계수 | `26p17/references/regional_io_2020/2020지역_통합중분류_생산유발계수.xlsx` | KOSIS `DT_301010_FILE20201` file_sn=4 |
| 부가가치유발계수 | `26p17/references/regional_io_2020/2020지역_통합중분류_부가가치유발계수.xlsx` | KOSIS 같은 표 file_sn=6 |
| 지역 취업유발 | `26p17/data/raw/고용표/2020지역_부속표_고용표_통합중분류.xlsx` | ECOS 2.2.1 → 2020 지역표 → 고용표 |

### KOSIS 자동 다운로드 (검증됨)
KOSIS 파일통계표 `DT_301010_FILE20201` = "(파일) 2020년 지역표". 2단계 AJAX:
1. `POST stat.kosis.kr/nsibsHtmlSvc/fileView/FileStbl/fileItmDownload.do` (org_id=301, tbl_id, file_sn, conn_path=E1) → JSON `{dwldFilePath, dwldFileNm, srvcNm}`
2. `POST .../dwldServerFile.do` (+ file_path, file_name) → xlsx 바이트
httpx 세션 쿠키로 재현 OK. file_sn: 2=총거래표, 3=총투입계수, 4=생산유발, 5=수입유발, 6=부가가치유발, 12·14=통합소분류.

### 주의 (함정)
- 처음 받았던 `(표)(2023연장)부속표_고용표_*`는 **전국(국가) 고용표** — 지역 차원 없음, 지역 산정 불가.
- 필요한 건 **`2020지역_부속표_고용표_*`** (행에 서울/…/제주 × 83부문).
- 한국은행 **지역** IO는 깨끗한 API 없음(ECOS/공공데이터포털은 전국표). KOSIS 파일통계표 또는 ECOS에서 xlsx 받아야 함. 5년 주기(…2010·2013·2015·2020).

---

## 5. 코드 구조

```
rio-mcp/
  pyproject.toml          # mcp, pandas, openpyxl, httpx; entry-point korea-rio-mcp
  README.md               # 설치 + codex/gemini/claude MCP 설정 스니펫
  STATUS.md               # 이 문서
  scripts/build_coefficients_2020.py   # 17지역 CSV 생성 (원본 xlsx → 계수)
  src/rio_mcp/
    server.py             # FastMCP stdio; 도구 6 + 프롬프트 2
    engine/
      coefficients.py     # 계수 로드/추출 (제주합 행 방식 — 레거시 단일지역)
      multiregional.py    # 다지역 행블록 합산 추출 (신, 17지역용)
      effects.py          # 정책지출·행사현장·부수체류 효과 + summarize()
      regions.py          # 레거시 단일지역 레이아웃 레지스트리 (제주 시드)
      defaults.py         # 표준 파라미터(1인당지출·목적성가중치 등) 기본값
    data_source/bok.py    # 베이스표 점검/입수 (※ 아직 구 BOK 보도자료 가정)
    docs/report.py        # interim/final 표 렌더 (None→N/A 처리)
    store/cache.py        # region+year 버전 계수 캐시 (cache dir → bundled 순)
    data/coefficients/    # 번들된 17개 지역 CSV (3지표)
    data/reference/       # 부수체류 KTO 단가·매핑 (제주/전국)
  tests/test_golden_jeju.py   # 8 tests
  tests/fixtures/         # 제주 레거시 계수 + P09 지출맵
```

### MCP 도구/프롬프트
- 도구: `rio_list_coefficients`, `rio_check_base_table_update`, `rio_load_base_table`, `rio_compute_effects`, `rio_compute_event`, `rio_render_report`
- 프롬프트: `map_budget_to_sectors`, `documentation_standard`

---

## 6. 빠른 실행

```bash
cd /Users/namun/dev/rio-mcp
pip install -e .            # 또는 uvx --from . korea-rio-mcp
pytest                     # 골든 8개

# 17개 지역 재생성 (원본 xlsx 경로는 26p17 — 위 표 참조)
python scripts/build_coefficients_2020.py \
  --prod ".../2020지역_통합중분류_생산유발계수.xlsx" \
  --va   ".../2020지역_통합중분류_부가가치유발계수.xlsx" \
  --emp  ".../2020지역_부속표_고용표_통합중분류.xlsx" \
  --out src/rio_mcp/data/coefficients
```

엔진 직접 호출 예:
```python
from rio_mcp.engine.coefficients import load_coefficients
from rio_mcp.engine.effects import policy_expenditure_effects, summarize
from rio_mcp.store import cache
coef = load_coefficients(cache.resolve_path("강원", 2020, "중분류(83부문)"))
print(summarize(policy_expenditure_effects(coef, "tests/fixtures/spending_industry_mapping_p09.csv")))
```

---

## 7. 남은 작업 (옵션, 우선순위 무관)

1. **`bok.py` / `rio_load_base_table` 업그레이드** — 현재 구 BOK 보도자료 가정. 검증된 KOSIS `DT_301010_FILE20201` 2단계 다운로드 경로로 자동 입수 구현. 취업은 지역 부속표_고용표 별도 입수 경로 필요.
2. **통합소분류(더 세분)** — 동일 알고리즘으로 추출 가능(file_sn 12·14 + 소분류 고용표). 현재 중분류 83만 빌드.
3. **`regions.py`(레거시 제주합 방식)와 `multiregional.py`(신 행블록 방식) 정리** — 추출 경로 2개 공존. 단일화 검토.
4. **26p17 본문 재생성** — 이 엔진 산출로 챕터 표 갱신(별개 트랙). 참고: [[feedback_final_report_table_standard]] — 중간보고 생산유발만, 최종보고 3지표.
5. **부수체류/이벤트 파라미터** — `data/reference`의 KTO 단가는 제주·여름가중. 타 지역·계절 적용 시 `monthly_weight`·단가 검토.

---

## 8. 관련 위치
- 본 프로젝트: `/Users/namun/dev/rio-mcp`
- 모태/소비자(첫 검증 사례): `/Users/namun/dev/26p17-seogwipo-policy-impact` (서귀포 보고서, 원본 xlsx 보관)
- 메모리: `project_rio_mcp_repo.md` (이 작업 요약), `project_rio_data_pipeline_state.md` (26p17 RIO 파이프라인)
