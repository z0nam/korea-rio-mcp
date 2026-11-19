"""cache.save must be atomic: no temp leftovers, readers never see partial files."""
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from rio_mcp.store import cache


def test_save_is_atomic_under_concurrency(tmp_path, monkeypatch):
    monkeypatch.setenv("RIO_MCP_CACHE_DIR", str(tmp_path))
    df = pd.DataFrame({"sector_code": [f"{i:02d}" for i in range(1, 84)],
                       "v": [float(i) for i in range(83)]})

    def save_then_read(_):
        cache.save(df, "테스트", 2020)
        return pd.read_csv(cache.resolve_path("테스트", 2020), dtype={"sector_code": str})

    with ThreadPoolExecutor(8) as ex:
        reads = list(ex.map(save_then_read, range(32)))

    assert all(len(r) == 83 for r in reads)
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []
    assert pd.read_csv(cache.resolve_path("테스트", 2020), dtype={"sector_code": str}).equals(df)
