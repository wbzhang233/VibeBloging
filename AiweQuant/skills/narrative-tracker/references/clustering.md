# 叙事聚类方法与增量更新

## 聚类算法选型

使用 **HDBSCAN**（Hierarchical DBSCAN）而非 K-Means 的原因：
- 不需要预设簇数量（叙事数量动态变化）
- 能识别噪声点（单条孤立资讯不强行归类）
- 支持不同密度的簇（热门叙事 vs 冷门叙事）

```python
from sentence_transformers import SentenceTransformer
from hdbscan import HDBSCAN
import numpy as np

embedder = SentenceTransformer("all-MiniLM-L6-v2")  # 轻量快速

def cluster_narratives(summaries: list[str], min_cluster_size: int = 5):
    embeddings = embedder.encode(summaries, batch_size=64, show_progress_bar=True)
    # L2 归一化（余弦相似度等价于欧式距离）
    embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

    clusterer = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=3,
        metric="euclidean",
        cluster_selection_method="eom",  # Excess of Mass，簇边界更稳定
        prediction_data=True,            # 支持增量软分配
    )
    labels = clusterer.fit_predict(embeddings)
    return labels, clusterer, embeddings
```

## 增量更新策略

新资讯到来时，不重新聚类全量数据（成本高），而是用**软分配**（Soft Assignment）判断新资讯归属：

```python
from hdbscan.prediction import membership_vector

def assign_new_record(record_embedding, clusterer, existing_embeddings):
    """将新资讯软分配到现有叙事，或识别为新叙事种子"""
    normalized = record_embedding / np.linalg.norm(record_embedding)

    # 软分配：返回对每个簇的归属概率
    probs = membership_vector(clusterer, normalized.reshape(1, -1))[0]
    best_cluster = np.argmax(probs)
    best_prob = probs[best_cluster]

    if best_prob > 0.5:
        return best_cluster  # 归属到现有叙事
    else:
        return -1  # 新叙事种子（积累足够数量后触发重聚类）
```

**重聚类触发条件**：
- 累积超过 N 条孤立资讯（默认 N=20）
- 距上次全量聚类超过 72 小时
- 手动触发（研究员判断市场叙事结构已发生重大切换）

## 叙事标签生成

对每个聚类用 LLM 自动生成可读标签：

```python
def generate_narrative_label(cluster_summaries: list[str], client) -> str:
    sample = cluster_summaries[:5]  # 取最新5条作为代表
    prompt = f"""以下是一组相关金融资讯摘要，请用5-10个中文字概括它们共同讨论的核心主题：
{chr(10).join(f'- {s}' for s in sample)}
输出格式：只输出主题标签，不含解释。"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=20,
    )
    return response.choices[0].message.content.strip()
```

## 嵌入模型选择

| 模型 | 速度 | 质量 | 适用场景 |
|------|------|------|---------|
| `all-MiniLM-L6-v2` | 快 | 中 | 实时流式更新 |
| `all-mpnet-base-v2` | 中 | 高 | 离线批量聚类 |
| `text-embedding-3-small` (OpenAI) | 慢（API） | 高 | 精度优先场景 |

**推荐**：本地实时处理用 `all-MiniLM-L6-v2`；历史数据全量聚类用 `all-mpnet-base-v2`。
