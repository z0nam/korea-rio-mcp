[English](README.md) | **한국어**

# korea-rio-mcp

한국은행 지역산업연관표 기반의 **지역 경제적 파급효과(Regional Input-Output, RIO) 분석을
크로스플랫폼 MCP 서버**로 제공합니다. 특정 지역에서 일어나는 경제적 이벤트에 대해
생산·부가가치·고용 유발효과를 (지역내 / 지역외로 분리하여) 계산합니다. Claude Code,
Codex, Gemini CLI에서 stdio로 동작합니다.

서귀포 축제 파급효과 분석(26p17)에서 일반화했으며, 제주 2020년 표를 검증된 골든 케이스로
함께 배포합니다.

OECD-MCP, bcrp-mcp처럼 공표된 통계를 *조회*만 하는 MCP 서버와 달리, korea-rio-mcp는
지역 산업연관 계수로부터 유발 파급효과를 직접 *계산*합니다 — IMPLAN 같은 상용 도구의
오픈소스·MCP 네이티브 대안을 한국은행 지역산업연관표 위에 구현한 것입니다.

## 하는 일

1. **기초표 확보** — 한국은행이 새 지역산업연관표 기준연도를 공표했는지 확인하고,
   해당 워크북에서 버전 관리되는 유발계수를 추출합니다.
2. **효과 계산** — 이벤트 지출(정책 집행비 + 외지 방문객 현장 소비 + 부대 체류)에
   유발계수를 적용하되, 신뢰도 높은 정책 채널과 변동이 큰 참가자 채널을 분리해서 둡니다.
3. **문서화** — 표준화된 마크다운 효과표를 렌더링합니다(중간보고: 생산만 / 최종보고: 3개 지표 전부).

## 설치

```bash
# GitHub에서 설치 (실사용자 권장):
uv tool install git+https://github.com/z0nam/korea-rio-mcp

# 로컬 체크아웃에서 설치 (개발용):
pip install -e .        # 또는: uvx --from . korea-rio-mcp
```

Python 3.10 이상이 필요합니다. 제주 2020년 중분류(83부문) 계수표가 번들로 포함돼 있어
효과 계산은 설치 직후 바로 동작합니다.

## 도구(Tools)

| 도구 | 용도 |
|---|---|
| `rio_list_coefficients` | 사용 가능한 계수표 목록(캐시/번들) |
| `rio_check_base_table_update` | 한국은행의 새 지역산업연관표 기준연도 확인 |
| `rio_load_base_table` | 한국은행 워크북에서 계수 추출 + 캐시 |
| `rio_compute_effects` | 부문 단위 지출에 대한 효과 계산 |
| `rio_compute_event` | 이벤트 통합 효과(정책+방문객 채널, 분리 유지) |
| `rio_render_report` | 표준 마크다운 효과표(`interim` / `final`) |

프롬프트: `map_budget_to_sectors`, `documentation_standard` — 판단이 많이 필요한 단계
(예산→부문 매핑, 보고 톤)는 의도적으로 LLM 계층에 맡겨 둡니다.

## MCP 클라이언트 설정

서버는 `korea-rio-mcp` 콘솔 스크립트(stdio 전송)로 실행합니다.

**Claude Code** — 프로젝트의 `.mcp.json` (또는 `claude mcp add`):

```json
{
  "mcpServers": {
    "korea-rio": { "command": "korea-rio-mcp" }
  }
}
```

`claude mcp add`로 한 줄로도 등록할 수 있습니다:

```bash
claude mcp add korea-rio -- korea-rio-mcp
```

**Codex** — `~/.codex/config.toml`:

```toml
[mcp_servers.korea_rio]
command = "korea-rio-mcp"
```

**Gemini CLI** — `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "korea-rio": { "command": "korea-rio-mcp" }
  }
}
```

`korea-rio-mcp`가 PATH에 없으면 콘솔 스크립트의 절대 경로(또는
`python -m rio_mcp.server`)를 사용하세요.

## 지역 추가하기

유발계수 추출에는 한국은행 워크북에서 각 지역의 소계(subtotal) 행 위치가 필요합니다.
`src/rio_mcp/engine/regions.py`에 `RegionTableLayout`을 등록(제주 2020 항목이 작성 예시)한 뒤
`rio_load_base_table`을 호출하세요.

## 데이터 참고

한국은행 **지역** 산업연관표는 깔끔한 API로 제공되지 않습니다. 비정기적으로(약 5년 주기:
2003 → 2005 → 2010 → 2013 → 2015 → 2020)
[한국은행 간행물](https://www.bok.or.kr/portal/singl/newsData/list.do?menuNo=200457)에
엑셀 파일로 공표됩니다. `rio_check_base_table_update`가 최신 공표 연도와 다운로드 URL을
알려주며, 이후 수동 다운로드 + `rio_load_base_table`로 적재합니다.

## 테스트

```bash
pytest    # 골든 테스트: 26p17 제주 2020 수치 재현
```

## 데이터 출처 및 출처 표시

번들된 계수표(`data/coefficients/`, `data/reference/`)는 한국은행(Bank of Korea)
지역산업연관표(2020년 기준)에서 **추출·가공한 파생물**입니다. 원본은
[한국은행 간행물](https://www.bok.or.kr/portal/singl/newsData/list.do?menuNo=200457)에서
공표됩니다.

- **출처: 한국은행 (Bank of Korea).**
- 이 파일들은 한국은행 원본 워크북이 **아니라**, 거기서 추출·변환한 유발계수
  (생산/부가가치/고용, 지역내/지역외 구분)입니다.
- 한국은행 데이터 이용은
  [한국은행 저작권보호방침](https://www.bok.or.kr/portal/main/contents.do?menuNo=200228)을
  따르며, 출처(한국은행) 표시와 수정·가공 사실의 명시가 요구됩니다.

## 라이선스

MIT 라이선스([`LICENSE`](LICENSE) 참조)는 **소프트웨어에만** 적용됩니다. 기반이 되는
한국은행 통계 데이터에는 적용되지 않으며, 해당 데이터 이용은 위에 링크된 한국은행
저작권보호방침을 따릅니다.
