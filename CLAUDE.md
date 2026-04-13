# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VibeBloging is an AI-assisted technical blogging and archival project. Content is primarily Markdown. There is no build system, package manager, or test suite — this is a documentation and knowledge management project.

## Project Structure

```text
VibeBloging/
├── _project/           — memory.md (reverse-chrono) + log.md (operations)
├── Agent/              — Research articles on Claude Code, AI agents, workflow automation (12 files, numbered)
├── AiweQuant/          — AI/Agent in quantitative investment research blog series
│   └── skills/         — 4 reusable Claude Code Skills
├── HermesAgent/        — Agent framework analysis series (Claude Code / OpenClaw / HermesAgent)
├── InsightClaudeCode/  — Claude Code precision teardown series (notes/ + figures/)
├── LearningClaudeCode/ — Claude Code learning series (research/ + images/)
└── materials/          — Archived reference materials (web clippings, PDFs)
```

## Directory Details

### Agent/ (12 articles, numbered)

Research on Claude Code internals, AI agent frameworks, and workflow automation.

#### Claude Code Series (01–03)

- `01_ClaudeCode技术解析报告.md` — Four-layer architecture, 45+ tools, command system
- `02_FunctionCall_MCP_Tools_Skills_Harness深度解析.md` — Tool Use protocol, Harness, Multi-Agent
- `03_VibeCoding_with_ClaudeCode.md` — Vibe Coding philosophy and workflow

#### Skills Series (04–06)

- `04_ClaudeCode_Skills完全指南.md` — Complete Claude Code Skills guide
- `05_AI工作流Skills完全指南.md` — Platform-agnostic AI workflow skills guide
- `06_AI工作流Skills实战指南_业务人员版.md` — Business-user Skills guide (finance focus)

#### Agent Frameworks Series (07–12)

- `07_Agent设计方法论.md` — Agent design patterns via OpenClaw 8-file framework
- `08_OpenClaw深度解析.md` — OpenClaw deep analysis
- `09_国内AI_Claw工具调研报告.md` — Chinese AI Claw tools survey
- `10_开源多智能体框架全景调研.md` — AgentScope/AutoGen/CrewAI/MetaGPT/LangGraph comparison
- `11_n8n工作流自动化深度解析.md` — n8n workflow automation analysis
- `12_豆包Agent定义.md` — Doubao Agent framework analysis

### AiweQuant/ (2 blogs + 4 skills)

Blog series on news-flow driven quantitative strategies using AI/LLM.

#### Blogs

- `01_AIAgent赋能资讯流策略研发.md` — NSIF factor framework, LLM extraction, factor validation
- `02_资讯流外汇贵金属策略构建实践.md` — Strategy construction A-F framework, walk-forward validation

#### Skills (`skills/<name>/SKILL.md` + scripts)

- `news-analyzer` — Unstructured news → structured sentiment scores
- `narrative-tracker` — Narrative lifecycle tracking and clustering
- `nsif-computer` — NSIF factor computation pipeline
- `bond-factor-miner` — Complete bond factor mining pipeline (6 factor classes, IC validation)

### HermesAgent/ (4 blogs + 5 HTML visualizations)

Analysis of HermesAgent, OpenClaw, and Claude Code frameworks.

#### HermesAgent Blogs

- `01_HermesAgent深度解析.md` — HermesAgent single-agent persistent loop, 4-layer memory
- `02_三款Agent横向对比_ClaudeCode_OpenClaw_HermesAgent.md` — Six-dimension comparison
- `03_ClaudeCode与HermesAgent的对比.md` — Focused CC vs Hermes comparison
- `04_HermesAgent自进化机制：Skill自学习与自修复架构深度解析.md` — Skill self-learning & hot-patch mechanism

`images/` contains 5 interactive self-contained HTML visualizations (dark theme, glassmorphism).

### InsightClaudeCode/ (precision teardown, 2026-04-10)

- `notes/` — 9 technical deep-dives (00–08): architecture, request lifecycle, permissions, context compression, tool execution, coordinator-worker, memory, hooks, MCP
- `figures/` — 8 interactive HTML visualizations matching the series

### LearningClaudeCode/ (learning series)

- `research/` — 7 structured learning documents (01–07)
- `images/` — 7 interactive HTML visualizations

## Working Conventions

- **After each significant conversation or task**, summarize key decisions and new content in `_project/memory.md` (reverse-chronological order) and log operations in `_project/log.md`.
- Blog posts live in their respective subdirectory and are numbered sequentially.
- Skills are defined in `AiweQuant/skills/<skill-name>/SKILL.md` with supporting scripts alongside.
- HTML visualizations: fully self-contained (Google Fonts CDN only external dependency).
- Design standard: `#030712` background, `#3b82f6` Claude blue, Space Grotesk + JetBrains Mono.

## Skills Framework

Reusable Claude Code Skills are stored under `AiweQuant/skills/`. Each skill directory contains:

- `SKILL.md` — skill definition (task description, inputs, outputs, references)
- Supporting Python scripts or data files for the skill's pipeline

Current skills: `news-analyzer`, `narrative-tracker`, `nsif-computer`, `bond-factor-miner`.

## Content Domain Context

The AiweQuant blog covers a specific quantitative strategy research workflow:

- **NSIF (Net Sentiment Intensity Factor)**: direction × intensity × confidence × source_weight × time_decay, decomposed by `logic_tag`
- **Time decay**: hard data (half-life 1–4h), geopolitical (12–72h), research reports (3–7 days)
- **LLM confidence**: raw scores need Platt Scaling calibration (raw scores are systematically high)
- **Factor validation thresholds**: IC > 0.05, ICIR > 0.5
