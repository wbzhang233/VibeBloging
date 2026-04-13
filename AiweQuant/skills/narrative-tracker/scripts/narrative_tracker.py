#!/usr/bin/env python3
"""
NarrativeTracker — 宏观叙事识别与动量追踪
用法: python narrative_tracker.py --input structured.jsonl --output narratives.jsonl --state tracker_state.pkl
"""

import json
import pickle
import argparse
import hashlib
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict

try:
    import numpy as np
    import pandas as pd
    from sentence_transformers import SentenceTransformer
    from hdbscan import HDBSCAN
except ImportError:
    print("请安装依赖: pip install sentence-transformers hdbscan numpy pandas")
    raise

# ── 配置 ──────────────────────────────────────────────────────────────────────

LIFECYCLE_CONFIG = {
    "emerging_threshold":    10,
    "fading_gap_hours":      48,
    "max_age_days":          30,
    "min_age_to_close_days":  3,
    "momentum_short_window": "24H",
    "momentum_long_window":  "72H",
}

HDBSCAN_CONFIG = {
    "min_cluster_size": 5,
    "min_samples":      3,
    "metric":           "euclidean",
    "cluster_selection_method": "eom",
    "prediction_data":  True,
}


# ── 核心类 ─────────────────────────────────────────────────────────────────────

class NarrativeTracker:
    def __init__(
        self,
        embedding_model: str = "all-MiniLM-L6-v2",
        config: dict = None,
    ):
        self.embedder = SentenceTransformer(embedding_model)
        self.config = config or LIFECYCLE_CONFIG
        self.narratives: dict[str, dict] = {}   # narrative_id → narrative dict
        self._clusterer = None
        self._all_embeddings = []
        self._all_record_ids = []
        self._pending_orphans = []              # 待分配的孤立资讯

    # ── 状态管理 ──────────────────────────────────────────────────────────────

    def save_state(self, path: str):
        with open(path, "wb") as f:
            pickle.dump({
                "narratives":       self.narratives,
                "clusterer":        self._clusterer,
                "all_embeddings":   self._all_embeddings,
                "all_record_ids":   self._all_record_ids,
                "pending_orphans":  self._pending_orphans,
            }, f)

    def load_state(self, path: str):
        with open(path, "rb") as f:
            state = pickle.load(f)
        self.narratives      = state["narratives"]
        self._clusterer      = state["clusterer"]
        self._all_embeddings = state["all_embeddings"]
        self._all_record_ids = state["all_record_ids"]
        self._pending_orphans = state.get("pending_orphans", [])

    # ── 核心更新 ──────────────────────────────────────────────────────────────

    def update(self, records: list[dict]):
        """增量更新：处理新一批结构化资讯"""
        if not records:
            return

        summaries = [r.get("content_summary") or r.get("keywords", [""])[0] for r in records]
        embeddings = self.embedder.encode(summaries, batch_size=32)
        embeddings = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-10)

        for record, emb in zip(records, embeddings):
            self._process_record(record, emb)

        # 积累足够孤立资讯后重新聚类
        if len(self._pending_orphans) >= 20:
            self._recluster()

        self._update_lifecycle()

    def _process_record(self, record: dict, embedding: np.ndarray):
        """将单条资讯分配到叙事"""
        if self._clusterer is None or len(self._all_embeddings) < 10:
            self._pending_orphans.append((record, embedding))
            self._all_embeddings.append(embedding)
            self._all_record_ids.append(record.get("news_id", ""))
            if len(self._all_embeddings) >= 20:
                self._recluster()
            return

        # 软分配到现有叙事
        narrative_id = self._soft_assign(embedding)
        if narrative_id:
            self._add_to_narrative(narrative_id, record)
        else:
            self._pending_orphans.append((record, embedding))
        self._all_embeddings.append(embedding)
        self._all_record_ids.append(record.get("news_id", ""))

    def _soft_assign(self, embedding: np.ndarray) -> str | None:
        """软分配：返回最匹配的 narrative_id 或 None"""
        if not self.narratives:
            return None
        best_id, best_sim = None, 0.4  # 相似度阈值
        for nid, narrative in self.narratives.items():
            if narrative["status"] == "closed":
                continue
            centroid = narrative.get("centroid")
            if centroid is None:
                continue
            sim = float(np.dot(embedding, centroid))
            if sim > best_sim:
                best_sim, best_id = sim, nid
        return best_id

    def _recluster(self):
        """全量重聚类"""
        if len(self._all_embeddings) < HDBSCAN_CONFIG["min_cluster_size"]:
            return
        embs = np.array(self._all_embeddings)
        clusterer = HDBSCAN(**HDBSCAN_CONFIG)
        labels = clusterer.fit_predict(embs)
        self._clusterer = clusterer

        # 重建叙事字典
        cluster_records = defaultdict(list)
        for idx, label in enumerate(labels):
            if label == -1:
                continue
            nid = f"narrative_{label:04d}"
            cluster_records[nid].append(idx)

        for nid, indices in cluster_records.items():
            cluster_embs = embs[indices]
            centroid = cluster_embs.mean(axis=0)
            centroid /= np.linalg.norm(centroid) + 1e-10
            if nid not in self.narratives:
                self.narratives[nid] = {
                    "narrative_id":   nid,
                    "label":          f"叙事{nid}",
                    "status":         "emerging",
                    "created_at":     datetime.now(timezone.utc).isoformat(),
                    "last_updated":   datetime.now(timezone.utc).isoformat(),
                    "news_count":     0,
                    "records":        [],
                    "assets_impacted": [],
                    "logic_tags":     [],
                    "sentiment_series": [],
                    "momentum_score": 0.0,
                    "sentiment_trend": 0.0,
                    "centroid":       centroid,
                }
            else:
                self.narratives[nid]["centroid"] = centroid
        self._pending_orphans = []

    def _add_to_narrative(self, narrative_id: str, record: dict):
        """将记录添加到叙事"""
        n = self.narratives[narrative_id]
        n["records"].append(record)
        n["news_count"] = len(n["records"])
        n["last_updated"] = datetime.now(timezone.utc).isoformat()

        # 更新受影响标的
        for asset in record.get("assets", {}):
            if asset not in n["assets_impacted"]:
                n["assets_impacted"].append(asset)

        # 更新 logic_tags
        for tag in record.get("logic_tags", []):
            if tag not in n["logic_tags"]:
                n["logic_tags"].append(tag)

        # 追加情绪时序
        main_sentiment = 0.0
        for asset_data in record.get("assets", {}).values():
            main_sentiment += asset_data.get("direction", 0) * asset_data.get("impact", 0.5)
        n["sentiment_series"].append({
            "timestamp": record.get("timestamp"),
            "sentiment": main_sentiment / max(len(record.get("assets", {})), 1),
        })

    def _update_lifecycle(self):
        """更新所有叙事的生命周期状态和动量"""
        now = datetime.now(timezone.utc)
        cfg = self.config

        for n in self.narratives.values():
            if n["status"] == "closed":
                continue

            last_updated = datetime.fromisoformat(n["last_updated"])
            created_at   = datetime.fromisoformat(n["created_at"])
            age_days = (now - created_at).total_seconds() / 86400
            gap_hours = (now - last_updated).total_seconds() / 3600

            # 状态转移
            if n["news_count"] >= cfg["emerging_threshold"] and n["status"] == "emerging":
                n["status"] = "active"
            if gap_hours > cfg["fading_gap_hours"] and n["status"] == "active":
                n["status"] = "fading"
            if age_days > cfg["max_age_days"] and age_days > cfg["min_age_to_close_days"]:
                n["status"] = "closed"

            # 动量计算
            n["momentum_score"]  = self._calc_momentum(n["sentiment_series"])
            n["sentiment_trend"] = self._calc_trend(n["sentiment_series"])
            n["timeline_summary"] = self._build_timeline_summary(n["records"])

    def _calc_momentum(self, series: list[dict]) -> float:
        if len(series) < 2:
            return 0.0
        df = pd.DataFrame(series)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp").sort_index()
        short = df["sentiment"].rolling("24H").mean().iloc[-1]
        long_ = df["sentiment"].rolling("72H").mean().iloc[-1]
        if pd.isna(short) or pd.isna(long_):
            return 0.0
        return float(short - long_)

    def _calc_trend(self, series: list[dict]) -> float:
        if not series:
            return 0.0
        recent = series[-10:]
        return float(np.mean([r["sentiment"] for r in recent]))

    def _build_timeline_summary(self, records: list[dict], max_entries: int = 8) -> str:
        recent = sorted(records, key=lambda r: r.get("timestamp", ""))[-max_entries:]
        lines = []
        for r in recent:
            ts = (r.get("timestamp") or "")[:16]
            src = r.get("source", "?")
            kws = ", ".join(r.get("keywords", [])[:3])
            lines.append(f"[{ts}] {src}: {kws}")
        return "\n".join(lines)

    # ── 查询接口 ──────────────────────────────────────────────────────────────

    def get_active_narratives(self, min_news_count: int = 3) -> list[dict]:
        return [
            {k: v for k, v in n.items() if k not in ("records", "centroid", "sentiment_series")}
            for n in self.narratives.values()
            if n["status"] in ("emerging", "active") and n["news_count"] >= min_news_count
        ]

    def get_momentum(self, asset: str) -> float:
        """返回与某标的相关的所有活跃叙事的加权动量"""
        relevant = [n for n in self.narratives.values()
                    if asset in n.get("assets_impacted", []) and n["status"] == "active"]
        if not relevant:
            return 0.0
        return float(np.mean([n["momentum_score"] for n in relevant]))


# ── CLI 入口 ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NarrativeTracker — 叙事追踪")
    parser.add_argument("--input",  required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--state",  default="tracker_state.pkl", help="状态持久化文件")
    parser.add_argument("--min-news", type=int, default=3)
    args = parser.parse_args()

    tracker = NarrativeTracker()
    if Path(args.state).exists():
        tracker.load_state(args.state)
        print(f"[NarrativeTracker] 加载已有状态: {len(tracker.narratives)} 条叙事")

    records = [json.loads(l) for l in Path(args.input).read_text().splitlines() if l.strip()]
    tracker.update(records)

    active = tracker.get_active_narratives(min_news_count=args.min_news)
    Path(args.output).write_text(
        "\n".join(json.dumps(n, ensure_ascii=False) for n in active),
        encoding="utf-8"
    )
    tracker.save_state(args.state)
    print(f"[NarrativeTracker] 活跃叙事: {len(active)} 条 → {args.output}")


if __name__ == "__main__":
    main()
