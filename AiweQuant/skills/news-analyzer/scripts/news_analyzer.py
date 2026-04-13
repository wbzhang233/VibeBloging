#!/usr/bin/env python3
"""
NewsAnalyzer — 金融资讯结构化分析脚本
用法: python news_analyzer.py --input news.jsonl --output structured.jsonl
"""

import json
import argparse
import asyncio
from pathlib import Path
from typing import Optional
from datetime import datetime

try:
    from openai import AsyncOpenAI
    import numpy as np
except ImportError:
    print("请安装依赖: pip install openai numpy python-dotenv")
    raise

# ── 配置 ──────────────────────────────────────────────────────────────────────

DEFAULT_ASSETS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "XAUUSD", "XAGUSD"]

SOURCE_WEIGHTS = {
    "Reuters": 1.0, "Bloomberg": 1.0, "FT": 0.95, "WSJ": 0.95,
    "AP": 0.90, "SeekingAlpha": 0.65, "X": 0.40, "Reddit": 0.30,
}

SYSTEM_PROMPT = """你是一位专业的宏观对冲基金分析师，专注于G10外汇和贵金属（XAU/XAG）市场。
分析金融资讯，评估对各交易标的的多空影响。输出严格 JSON 格式，不含任何额外文字。"""

OUTPUT_SCHEMA = {
    "keywords": ["string"],
    "logic_tags": ["monetary_policy|geopolitics|macro_data|risk_sentiment|energy_commodity|fiscal_policy|positioning_flow"],
    "assets": {
        "<ASSET>": {
            "direction": "-1|0|+1",
            "impact": "float[0,1]",
            "confidence": "float[0,1]",
            "reasoning": "string"
        }
    },
    "event_importance": "float[0,1]",
    "novelty": "float[0,1]",
    "has_forward_guidance": "boolean"
}


# ── 核心分析函数 ───────────────────────────────────────────────────────────────

async def analyze_news(
    client: AsyncOpenAI,
    record: dict,
    assets: list[str] = DEFAULT_ASSETS,
    model: str = "gpt-4o",
    temperature: float = 0.2,
) -> dict:
    """分析单条资讯，返回结构化 Schema"""

    user_prompt = f"""分析以下金融资讯，按 Schema 输出 JSON。

资讯：
- 来源: {record.get('source', 'Unknown')}
- 时间: {record.get('timestamp', '')}
- 内容: {record.get('content', '')}

分析标的: {', '.join(assets)}
（受影响极小的标的：direction=0, impact<0.1）

Schema:
{json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, indent=2)}"""

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=temperature,
    )

    result = json.loads(response.choices[0].message.content)
    result["news_id"] = record.get("id", "")
    result["timestamp"] = record.get("timestamp", "")
    result["source"] = record.get("source", "")
    result["source_weight"] = SOURCE_WEIGHTS.get(record.get("source", ""), 0.5)
    result["narrative_id"] = None
    return result


async def analyze_batch(
    records: list[dict],
    assets: list[str] = DEFAULT_ASSETS,
    model: str = "gpt-4o",
    confidence_floor: float = 0.5,
    novelty_floor: float = 0.3,
    concurrency: int = 5,
) -> list[dict]:
    """批量分析，带并发控制和质量过滤"""
    client = AsyncOpenAI()
    semaphore = asyncio.Semaphore(concurrency)

    async def safe_analyze(record):
        async with semaphore:
            try:
                result = await analyze_news(client, record, assets, model)
                # 质量过滤
                for asset in list(result.get("assets", {}).keys()):
                    asset_data = result["assets"][asset]
                    if asset_data.get("confidence", 0) < confidence_floor:
                        del result["assets"][asset]  # 低置信度资产直接丢弃
                if result.get("novelty", 1.0) < novelty_floor:
                    result["_low_novelty"] = True  # 标记为重复，后续降权
                return result
            except Exception as e:
                print(f"[WARN] 分析失败: {record.get('id', '?')} — {e}")
                return None

    tasks = [safe_analyze(r) for r in records]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


# ── CLI 入口 ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NewsAnalyzer — 金融资讯结构化分析")
    parser.add_argument("--input",  required=True, help="输入 JSONL 文件路径")
    parser.add_argument("--output", required=True, help="输出 JSONL 文件路径")
    parser.add_argument("--assets", default=",".join(DEFAULT_ASSETS), help="分析标的（逗号分隔）")
    parser.add_argument("--model",  default="gpt-4o", help="LLM 模型")
    parser.add_argument("--concurrency", type=int, default=5, help="并发请求数")
    parser.add_argument("--confidence-floor", type=float, default=0.5)
    parser.add_argument("--novelty-floor",    type=float, default=0.3)
    args = parser.parse_args()

    records = [json.loads(line) for line in Path(args.input).read_text(encoding="utf-8").splitlines() if line.strip()]
    assets  = [a.strip() for a in args.assets.split(",")]

    print(f"[NewsAnalyzer] 处理 {len(records)} 条资讯，标的: {assets}")
    results = asyncio.run(analyze_batch(
        records, assets=assets, model=args.model,
        confidence_floor=args.confidence_floor,
        novelty_floor=args.novelty_floor,
        concurrency=args.concurrency,
    ))

    Path(args.output).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results),
        encoding="utf-8"
    )
    print(f"[NewsAnalyzer] 完成: {len(results)}/{len(records)} 条写入 {args.output}")


if __name__ == "__main__":
    main()
