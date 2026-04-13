#!/usr/bin/env python3
"""
NSIFComputer — 净情绪强度因子计算
用法: python nsif_computer.py --input structured.jsonl --assets EURUSD,XAUUSD --output nsif.parquet
"""

import json
import argparse
import math
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

try:
    import pandas as pd
    import numpy as np
except ImportError:
    print("请安装依赖: pip install pandas numpy pyarrow")
    raise

# ── 默认衰减参数 ───────────────────────────────────────────────────────────────

DEFAULT_LAMBDA = {
    "macro_data":        {"lambda": 0.347, "window_hours": 12},
    "monetary_policy":   {"lambda": 0.058, "window_hours": 72},
    "geopolitics":       {"lambda": 0.019, "window_hours": 168},
    "risk_sentiment":    {"lambda": 0.087, "window_hours": 48},
    "energy_commodity":  {"lambda": 0.029, "window_hours": 96},
    "fiscal_policy":     {"lambda": 0.014, "window_hours": 168},
    "positioning_flow":  {"lambda": 0.010, "window_hours": 240},
    "research_report":   {"lambda": 0.006, "window_hours": 360},
    "_default":          {"lambda": 0.058, "window_hours": 72},
}


# ── 核心计算 ───────────────────────────────────────────────────────────────────

class NSIFComputer:
    def __init__(self, lambda_config: dict = None):
        self.lambda_config = lambda_config or DEFAULT_LAMBDA

    def _get_lambda(self, tag: str, has_forward_guidance: bool = False) -> tuple[float, int]:
        cfg = self.lambda_config.get(tag, self.lambda_config["_default"])
        lam = cfg["lambda"]
        if has_forward_guidance:
            lam = lam / 3  # 前瞻指引衰减慢3倍
        return lam, cfg["window_hours"]

    def compute_point(
        self,
        records: list[dict],
        asset: str,
        tag: str,
        t: datetime,
    ) -> float:
        """计算单点 NSIF(t, asset, tag)"""
        lam, window_hours = self._get_lambda(tag)
        t_epoch = t.timestamp()

        numerator = 0.0
        denominator = 0.0

        for r in records:
            # 仅处理包含该 asset 且包含该 tag 的记录
            asset_data = r.get("assets", {}).get(asset)
            if asset_data is None:
                continue
            if tag not in r.get("logic_tags", []):
                continue

            # 时间过滤
            try:
                t_i = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            delta_t_hours = (t_epoch - t_i) / 3600
            if delta_t_hours < 0 or delta_t_hours > window_hours:
                continue

            direction   = asset_data.get("direction", 0)
            impact      = asset_data.get("impact", 0.5)
            confidence  = asset_data.get("confidence", 0.5)
            src_weight  = r.get("source_weight", 0.7)
            has_fg      = r.get("has_forward_guidance", False)

            lam_i = self._get_lambda(tag, has_fg)[0]
            decay = math.exp(-lam_i * delta_t_hours)

            # novelty 调整（低新颖度资讯降权）
            novelty_factor = 1.0 if r.get("novelty", 1.0) >= 0.3 else 0.5

            score = direction * impact * confidence * src_weight * novelty_factor
            numerator   += score * decay
            denominator += decay

        if denominator < 1e-10:
            return float("nan")
        return numerator / denominator

    def compute_series(
        self,
        structured_df: pd.DataFrame,
        asset: str,
        tag: str,
        freq: str = "1H",
        start: datetime = None,
        end: datetime = None,
    ) -> pd.Series:
        """计算 NSIF 时间序列"""
        records = structured_df.to_dict("records")
        timestamps = pd.date_range(
            start=start or structured_df["timestamp"].min(),
            end=end or structured_df["timestamp"].max(),
            freq=freq,
            tz="UTC",
        )
        values = [self.compute_point(records, asset, tag, t.to_pydatetime()) for t in timestamps]
        return pd.Series(values, index=timestamps, name=f"NSIF_{asset}_{tag}")

    def compute_matrix(
        self,
        structured_df: pd.DataFrame,
        assets: list[str],
        tags: list[str],
        freq: str = "1H",
    ) -> pd.DataFrame:
        """计算完整 NSIF 多维矩阵"""
        structured_df = structured_df.copy()
        structured_df["timestamp"] = pd.to_datetime(structured_df["timestamp"], utc=True)

        series_list = []
        for asset in assets:
            for tag in tags:
                s = self.compute_series(structured_df, asset, tag, freq)
                series_list.append(s)

        return pd.concat(series_list, axis=1)


# ── CLI 入口 ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NSIFComputer — NSIF 因子计算")
    parser.add_argument("--input",  required=True)
    parser.add_argument("--assets", required=True, help="逗号分隔，如 EURUSD,XAUUSD")
    parser.add_argument("--tags",   default=",".join(DEFAULT_LAMBDA.keys() - {"_default"}))
    parser.add_argument("--freq",   default="1H")
    parser.add_argument("--output", required=True, help=".parquet 或 .csv")
    args = parser.parse_args()

    records = [json.loads(l) for l in Path(args.input).read_text().splitlines() if l.strip()]
    df = pd.json_normalize(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    assets = [a.strip() for a in args.assets.split(",")]
    tags   = [t.strip() for t in args.tags.split(",") if t.strip() in DEFAULT_LAMBDA]

    computer = NSIFComputer()
    matrix = computer.compute_matrix(df, assets, tags, freq=args.freq)

    if args.output.endswith(".parquet"):
        matrix.to_parquet(args.output)
    else:
        matrix.to_csv(args.output)
    print(f"[NSIFComputer] 完成: {matrix.shape} → {args.output}")


if __name__ == "__main__":
    main()
