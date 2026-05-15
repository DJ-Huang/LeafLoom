from __future__ import annotations

import json
from typing import Any


def sanitize_metadata_for_vector_store(meta: dict[str, Any]) -> dict[str, str]:
    """
    LanceDB + Arrow 會對欄位推斷型別；若同一欄混用數字與空字串會失敗。
    因此將 **所有 metadata 值統一為字串**（缺值為空字串）。
    """
    out: dict[str, str] = {}
    for key, val in meta.items():
        sk = key if isinstance(key, str) else str(key)
        if val is None:
            out[sk] = ""
        elif isinstance(val, (dict, list, tuple)):
            out[sk] = json.dumps(val, ensure_ascii=False, default=str)
        else:
            out[sk] = str(val)
    return out
