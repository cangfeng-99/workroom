# 资料库语义检索（RAG）

给「项目资料库」加一层语义检索：能按意思找到相关规则/决策，回答带引用。
面试讲法：**资料库原来是给人看的，现在 AI 也能按语义查，而且回答必须给出处。**

## 链路

```
资料库条目 → 拼正文（标题 + 结论 + 内容 + 背景 + 备选 + 落地方式）
          → 切块（400 字，重叠 80）
          → 向量化（远程接口，未配置则本地哈希）
          → 存 DocumentChunk（SQLite，JSON 数组）
          → 提问：向量召回 TopK=8 + 关键词加分
          → 前 5 块拼 Prompt（带编号来源）
          → 模型生成（未配置则原文摘录，并明确标注）
```

## 数据

`DocumentChunk`：`project / entry / heading / content / embedding / dim / model / content_hash`。
索引按 `(project, model, dim)` 过滤，换向量模型时旧块自动判为 stale，需要重建。

## 配置（全部走环境变量，密钥不进代码）

| 变量 | 作用 | 不配的后果 |
|---|---|---|
| `WORKROOM_EMBED_BASE_URL` | 向量接口地址（到 `/v1` 为止） | 退化为本地哈希向量（关键词级） |
| `WORKROOM_EMBED_MODEL` | 向量模型名 | 使用 `hash-bigram-256` |
| `WORKROOM_EMBED_API_KEY` | 向量接口密钥 | — |
| `WORKROOM_RAG_CHAT_BASE_URL` | 回答用的对话接口 | 退化为原文摘录 |
| `WORKROOM_RAG_CHAT_MODEL` | 对话模型名 | — |
| `WORKROOM_RAG_CHAT_API_KEY` | 对话接口密钥 | — |
| `WORKROOM_VECTOR_STORE` | `sqlite`（默认）/ `chroma` | 用 SQLite 存向量并内存算余弦 |

## 命令

```bash
# 建/重建索引（不给 --project 则处理全部项目）
python workroom/manage.py rag_index --project 2
python workroom/manage.py rag_index --project 2 --force

# 跑评测集
python workroom/manage.py rag_eval --project 2 --file workroom/docs/rag-eval-sample.json --k 5
```

评测集格式：`[{"question": "...", "expect": ["关键词A", "关键词B"]}]`，命中任一关键词算该题命中。
样本见 `workroom/docs/rag-eval-sample.json`（当前 10 条，围绕册子项目两条决策）。

**实测结果（项目 #2，本地哈希向量）**

| 指标 | 结果 |
|---|---|
| Top-1 命中 | **9/10 = 90%**（失败：「没网能不能用」指到了冲突那条） |
| Top-5 命中 | 10/10 = 100%，但项目只有 2 块，Top-5 必然全中，**这个数字没有意义** |

结论：资料库只有 2 条时，评测只能当冒烟；要写进简历，得等资料库有几十条、并且配上真向量接口。

## 入口

| 入口 | 路径 |
|---|---|
| 页面 | `/p/<id>/knowledge/`（项目页「知识库问答」标签） |
| MCP 工具 | `ask_project_knowledge(project, question)` |
| 命令行 | `rag_index` / `rag_eval` |

## 取舍（面试会问）

1. **为什么不直接上向量库？**
   单人项目资料量在千级以内，SQLite 存 JSON + 内存余弦足够，少一个运维面。接口留了 `VectorStore` 形状，换 Chroma 只替换检索实现。
2. **切块为什么 400/80？**
   资料库条目多在 200-800 字，400 字一块命中率与上下文完整度的平衡；80 字重叠防止一句话被切断。
3. **没有向量接口时怎么办？**
   用字符 bigram 哈希向量 + 关键词加分，链路能跑通、能演示，但语义能力有限；这一点在页面和回答里都写明了，不假装是语义检索。
4. **怎么判断答得对？**
   自建评测集跑命中率，记录失败题；当前样本 2 题全中，属冒烟级别，不代表真实效果。

## 向量库可替换（已实现）

`apps/projects/vector_store.py` 提供两个实现：

| 实现 | 触发条件 | 说明 |
|---|---|---|
| `SqliteVectorStore` | 默认 | 向量存 `DocumentChunk`，内存算余弦；千级数据毫秒级 |
| `ChromaVectorStore` | `WORKROOM_VECTOR_STORE=chroma` | 懒加载 `chromadb`，未安装时给明确报错；`rag_index` 后自动同步 |

检索入口 `rag.search()` 不变，换实现不改业务代码。

## 还能加

- 重排序（Rerank）：召回 8 → 精排 5
- 引用高亮：答案里的 `[1]` 可点回资料条目
- 增量更新：已按 `content_hash` 跳过未变条目
