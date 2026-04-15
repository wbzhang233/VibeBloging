# Claude Code 完全使用指南：特性深析 × 实战技巧 × 最佳实践

> 作者：内部参考整理  
> 时间：2026-04-15  
> 标签：Claude Code + AI 编程 + 开发工具

---

## 写在前面

2025 年初，Anthropic 推出了 Claude Code —— 一款不同于以往 AI 聊天工具的终端级 AI 编程助手。

它被字节跳动、吴恩达等大厂和顶级开发者大力推荐，全网流传的「字节跳动内部 Claude Code 中文手册」更是引发了开发圈的广泛关注。

这篇文章，我们把所有分散的资料整合成一份完整的中文使用指南，**聚焦 Claude Code 的核心特性和实用技巧**，帮你真正用好这个工具。

> 核心观点：Claude Code 不是聊天工具，它是 **AI 编程代理（Agent）**。你给它目标，它自己规划、执行、验证。

---

## 一、Claude Code 到底是什么

### 1.1 定义：Agent，不是 Chat

Claude Code 和 ChatGPT、Claude 网页版最本质的区别在于：

| 特性 | Claude 网页版 | Claude Code |
|------|--------------|-------------|
| 交互方式 | 粘贴代码到对话框 | 直接在终端操作 |
| 文件访问 | 手动上传文件 | 自动读取整个工程目录 |
| 执行能力 | 仅生成文本 | 执行 Shell 命令、运行测试、创建文件 |
| 上下文感知 | 有限的对话上下文 | 深度感知项目结构和 Git 历史 |
| 工作模式 | 人驱动 AI | AI 自主规划执行 |

Claude Code 定位是：**在本地代码仓库中执行高权限、可上下文感知的工程任务**。

### 1.2 它能做什么

一句话描述一类任务，Claude Code 就能独立完成：

```bash
claude "write tests for the auth module, run them, and fix any failures"
claude "commit my changes with a descriptive message"
claude "find all deprecated API usage in our codebase"
```

具体来说，它能：

- 📁 **读取并理解整个代码库** —— 不只是你粘贴的片段
- ✏️ **跨多文件编写和修改代码** —— 一次搞定所有改动
- 🧪 **运行测试、执行命令、验证结果** —— 形成完整反馈循环
- 🔀 **管理 Git** —— 暂存、提交、创建分支、打开 PR
- 🔧 **连接外部工具（MCP）** —— Notion、Figma、数据库等
- 🤖 **运行多个子代理** —— 并行处理复杂任务

### 1.3 核心工作原理：Agentic Loop

```
你的指令 → Claude 探索代码库 → 制定计划 → 调用工具执行 → 验证结果 → 循环直到完成
```

不同于传统 AI 助手等你问问题，Claude Code **主动规划步骤并执行**。

---

## 二、安装与启动

### 2.1 安装方式

**macOS / Linux / WSL（推荐）：**

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

**Windows PowerShell：**

```powershell
irm https://claude.ai/install.ps1 | iex
```

**Homebrew（macOS）：**

```bash
brew install --cask claude-code
```

> ⚠️ Windows 原生安装需要先安装 [Git for Windows](https://git-scm.com/downloads/win)。原生安装会在后台自动更新；Homebrew 安装需手动运行 `brew upgrade claude-code`。

### 2.2 启动方式

进入任意项目目录，直接运行：

```bash
cd your-project
claude
```

**常用启动参数：**

| 命令 | 作用 |
|------|------|
| `claude` | 启动交互模式 |
| `claude -p "prompt"` | 非交互/无头模式（适合 CI/脚本） |
| `claude --continue` | 继续上次对话 |
| `claude --resume` | 选择历史对话恢复 |
| `claude -n session-name` | 以指定名称启动会话 |
| `claude --permission-mode plan` | 以规划模式启动（只读不执行） |
| `claude --worktree feature-name` | 在独立 worktree 中启动 |

---

## 三、使用场景快速入门

### 3.1 快速了解陌生代码库

加入新项目第一天，这样用：

```
give me an overview of this codebase
explain the main architecture patterns used here
what are the key data models?
how is authentication handled?
trace the login process from front-end to database
```

比看文档快 10 倍，比问同事更不打扰人。

### 3.2 修复 Bug

```
I'm seeing this error when I run npm test: [粘贴报错]
```

Claude Code 会：
1. 追踪问题根源
2. 找到相关文件
3. 编写失败测试复现问题
4. 应用修复并验证

### 3.3 编写测试

```
find functions in NotificationsService.swift that are not covered by tests
add tests for the notification service
add test cases for edge conditions
run the new tests and fix any failures
```

### 3.4 代码重构

```
find deprecated API usage in our codebase
refactor utils.js to use ES2024 features while maintaining the same behavior
run tests for the refactored code
```

### 3.5 创建 PR

```
summarize the changes I've made to the authentication module
create a pr
enhance the PR description with more context about the security improvements
```

---

## 四、核心功能深度解析

### 4.1 Plan Mode（规划模式）—— 最重要的工作流

**Plan Mode** 是 Claude Code 最有价值的功能之一。这个模式下，Claude **只分析不执行**，帮你制定完整计划后再动手。

**如何切换：**

- 启动时：`claude --permission-mode plan`
- 会话中：按 `Shift+Tab` 循环切换（Normal → Auto-Accept → Plan Mode）
- 看到 `⏸ plan mode on` 提示即生效
- 按 `Ctrl+G` 在编辑器中直接编辑计划

**推荐四步工作流：**

```
第一步：探索（Plan Mode）
→ "read /src/auth and understand how we handle sessions"

第二步：规划（Plan Mode）
→ "I want to add Google OAuth. What files need to change? Create a plan."

第三步：实现（切换回 Normal Mode 执行）
→ "implement the OAuth flow from your plan. write tests and fix any failures."

第四步：提交
→ "commit with a descriptive message and open a PR"
```

**什么时候用规划模式：**

- ✅ 修改涉及多个文件
- ✅ 不熟悉被修改的代码
- ✅ 复杂功能实现前
- ❌ 一句话能描述的小改动（拼写修复、加一行日志）→ 直接做

### 4.2 CLAUDE.md —— 给 Claude 的持久记忆文件

`CLAUDE.md` 是特殊文件，**Claude 在每次对话开始时自动读取**，用于存储项目规范、编码标准、工作流约定。

**快速生成：**

```bash
/init
```

Claude 会分析你的代码库，自动生成初始 `CLAUDE.md`。

**一个好的 CLAUDE.md 示例：**

```markdown
# Code style
- Use ES modules (import/export) syntax, not CommonJS (require)
- Destructure imports when possible
- Use 2-space indentation

# Workflow
- Typecheck when done making code changes
- Prefer running single tests, not the whole test suite
- Always run `npm run lint` before committing

# Architecture
- API handlers are in src/api/handlers/
- Database queries go in src/db/queries/
```

**放置位置：**

| 位置 | 范围 |
|------|------|
| `~/.claude/CLAUDE.md` | 所有项目（个人全局配置） |
| `./CLAUDE.md` 或 `./.claude/CLAUDE.md` | 当前项目（提交到 git，团队共享） |
| 子目录中的 `CLAUDE.md` | 子模块专属规则（按需加载） |

**写什么 vs. 不写什么：**

| ✅ 写进去 | ❌ 不要写 |
|---------|--------|
| Claude 猜不到的 Bash 命令 | Claude 能从代码推断的东西 |
| 与默认不同的代码风格规则 | 标准语言约定 |
| 测试指令和测试框架偏好 | 详细 API 文档（链接即可） |
| 分支命名、PR 约定 | 常识性"写干净代码" |
| 架构决策 | 逐文件描述代码库 |

> **重要**：CLAUDE.md 越短越好！超过 200 行会导致 Claude 忽略部分规则。每条规则问自己："删掉这条 Claude 会犯错吗？" 如果不会，删掉它。

**高级技巧 —— 导入其他文件：**

```markdown
# CLAUDE.md
See @README.md for project overview and @package.json for available npm commands.

# Additional Instructions
- Git workflow: @docs/git-instructions.md
```

### 4.3 自动记忆（Auto Memory）

从 v2.1.59 开始，Claude 会**自动为自己记笔记**，无需你手动维护：

- 构建命令
- 调试见解
- 代码风格偏好
- 工作流习惯

记忆文件存储在：`~/.claude/projects/<project>/memory/MEMORY.md`

**主动让 Claude 记住某件事：**

```
"记住：我们始终用 pnpm，不用 npm"
"记住：API 测试需要本地 Redis 实例"
```

运行 `/memory` 随时查看和编辑 Claude 保存的内容。

### 4.4 Hooks（钩子系统）—— 确定性自动化

Hooks 让你在 Claude 工作流的特定节点**自动运行脚本**。与 CLAUDE.md 指令不同，Hooks 是**确定性执行，100% 触发**。

**让 Claude 帮你生成 hook：**

```
"编写一个在每次文件编辑后运行 eslint 的 hook"
"编写一个阻止写入 migrations 文件夹的 hook"
"编写一个任务完成时发桌面通知的 hook"
```

**设置桌面通知（macOS 示例）：**

```json
{
  "hooks": {
    "Notification": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "osascript -e 'display notification \"Claude needs attention\" with title \"Claude Code\"'"
          }
        ]
      }
    ]
  }
}
```

运行 `/hooks` 查看所有配置的钩子。

### 4.5 MCP 集成 —— 连接外部世界

MCP（Model Context Protocol）是开放标准，让 Claude Code 连接外部数据源和工具。

```bash
claude mcp add
```

支持连接：

| 工具 | 用途 |
|------|------|
| Notion | 读取设计文档，按规范实现功能 |
| Figma | 直接从设计稿生成代码 |
| 数据库 | 查询数据，分析结构 |
| GitHub/Jira | 自动更新工单、创建 PR |
| Slack | 从错误报告路由到 PR |
| Google Drive | 读取规格文档 |

### 4.6 Sub-agents（子代理）—— 并行工作不污染 Context

每个子代理在**独立的 context 窗口**中运行，不消耗主对话的上下文。适合调查类任务。

**创建专属子代理（`.claude/agents/security-reviewer.md`）：**

```markdown
---
name: security-reviewer
description: Reviews code for security vulnerabilities
tools: Read, Grep, Glob, Bash
model: opus
---
You are a senior security engineer. Review code for:
- Injection vulnerabilities (SQL, XSS, command injection)
- Authentication and authorization flaws
- Secrets or credentials in code

Provide specific line references and suggested fixes.
```

**使用：**

```
use the security-reviewer subagent to check the auth module
use subagents to investigate how our authentication system handles token refresh
use a subagent to review this code for edge cases
```

### 4.7 Skills（技能）—— 可复用工作流

把团队常用流程打包成 skill，一个命令触发：

```markdown
<!-- .claude/skills/fix-issue/SKILL.md -->
---
name: fix-issue
description: Fix a GitHub issue
---
Analyze and fix the GitHub issue: $ARGUMENTS.

1. Use `gh issue view` to get the issue details
2. Search the codebase for relevant files
3. Implement the necessary changes to fix the issue
4. Write and run tests to verify the fix
5. Create a descriptive commit message and open a PR
```

使用：`/fix-issue 1234`

### 4.8 扩展思考（Thinking Mode）

Claude Code 支持 **ultrathink** 关键字，激活深度推理模式：

```
ultrathink: how should we architect the new payment system?
```

查看 Claude 的思考过程：按 `Ctrl+O` 切换详细模式，推理过程以灰色斜体显示。

**调整思考深度：**

- `/effort` 命令调整努力级别
- `Option+T` / `Alt+T` 切换 Thinking Mode 开关
- 环境变量 `CLAUDE_CODE_EFFORT_LEVEL` 全局配置

### 4.9 Worktrees（工作树）—— 并行会话隔离

同时处理多个任务，每个 Claude 会话用独立的 worktree，代码互不干扰：

```bash
# 在 feature-auth worktree 中启动 Claude
claude --worktree feature-auth

# 另一个窗口，独立的 bugfix worktree
claude --worktree bugfix-123
```

Worktree 在 `.claude/worktrees/<name>/` 下创建，有独立的分支。完成后 Claude 会自动提示保留或删除。

---

## 五、高效使用技巧

### 技巧 1：给 Claude 验证工作的方式（最高价值）

**这是最单项最高价值的习惯。** 当 Claude 能验证自己的工作，表现会显著提升。

| 策略 | ❌ 之前 | ✅ 之后 |
|------|--------|--------|
| 提供验证标准 | "实现一个验证邮箱的函数" | "编写 validateEmail 函数。测试：user@example.com 为真，invalid 为假。实现后运行测试" |
| 视觉验证 UI | "让仪表板看起来更好" | "[粘贴截图] 实现此设计，截图对比原始，列出差异并修复" |
| 解决根本原因 | "构建失败" | "构建失败，报错：[粘贴错误]。修复并验证成功，不要抑制错误" |

### 技巧 2：探索 → 规划 → 实现，三步走

永远先 Plan Mode 探索，再切 Normal Mode 执行，避免解决错误的问题。

### 技巧 3：具体的上下文 > 模糊的指令

| ❌ 模糊 | ✅ 具体 |
|--------|--------|
| "为 foo.py 添加测试" | "为 foo.py 编写测试，覆盖用户已注销的边界情况，避免 mock" |
| "修复登录错误" | "用户报告会话超时后登录失败，检查 src/auth/ 中的 token 刷新，编写失败测试后修复" |
| "添加日历组件" | "参照 HotDogWidget.php 的实现模式，实现支持月份选择和前后翻页的日历组件" |

**用 `@` 引用文件，比描述位置更高效：**

```
Explain the logic in @src/utils/auth.js
What's the structure of @src/components?
```

### 技巧 4：积极管理 Context 窗口

Context 是最稀缺的资源。随着填满，Claude 性能下降。

| 快捷键/命令 | 作用 |
|------------|------|
| `Esc` | 中途打断 Claude，context 保留 |
| `Esc+Esc` 或 `/rewind` | 打开回退菜单，恢复到之前状态 |
| `/clear` | 完全重置 context（不相关任务之间使用） |
| `/compact` | 压缩对话历史，释放空间 |
| `/compact Focus on API changes` | 带指令的精准压缩 |
| `/btw 你的问题` | 侧问，答案不进 context |

**黄金规则：不相关任务之间总是 `/clear`。同一问题纠正超过两次，直接 `/clear` 重来。**

### 技巧 5：让 Claude 先采访你

对于复杂功能，先让 Claude 来问你：

```
I want to build [brief description]. Interview me in detail using the AskUserQuestion tool.
Ask about technical implementation, UI/UX, edge cases, and tradeoffs.
Don't ask obvious questions, dig into the hard parts I might not have considered.
Keep interviewing until we've covered everything, then write a complete spec to SPEC.md.
```

然后**新开一个会话**来执行规范。全新 context + 完整规范 = 最佳效果。

### 技巧 6：用 Subagents 做调查，保护主 Context

```
Use subagents to investigate how our authentication system handles token refresh,
and whether we have any existing OAuth utilities I should reuse.
```

子代理读文件的消耗不进主 context，可以大胆探索。

### 技巧 7：命名你的会话，像管理分支一样

```bash
claude -n oauth-migration          # 启动时命名

# 会话中
/rename auth-refactor

# 稍后恢复
claude --resume auth-refactor
```

### 技巧 8：非交互模式 —— 集成进 CI/CD

```bash
# 一次性查询
claude -p "Explain what this project does"

# JSON 输出（适合脚本解析）
claude -p "List all API endpoints" --output-format json

# 管道输入
cat build-error.txt | claude -p "explain the root cause of this build error"

# CI 日志分析
tail -200 app.log | claude -p "Slack me if you see any anomalies"

# 集成进 package.json
# "lint:claude": "claude -p 'You are a linter. Look at changes vs. main and report typos.'"
```

### 技巧 9：Writer/Reviewer 双会话模式

| 会话 A（Writer） | 会话 B（Reviewer） |
|-----------------|------------------|
| `实现速率限制中间件` | |
| | `审查 @src/middleware/rateLimiter.ts，找边界情况、竞态条件和一致性问题` |
| `这是审查反馈：[B 的输出]，解决这些问题` | |

新鲜 context = 更客观的代码审查（不会偏向刚写的代码）。

### 技巧 10：大规模批处理 —— 跨文件扇出

```bash
# 列出所有需要迁移的文件
# 然后循环调用 Claude
for file in $(cat files.txt); do
  claude -p "Migrate $file from React to Vue. Return OK or FAIL." \
    --allowedTools "Edit,Bash(git commit *)"
done
```

---

## 六、常见错误与避坑

| 错误模式 | 症状 | 解法 |
|---------|------|------|
| 厨房水槽会话 | 一个对话干多件不相关的事 | 任务之间 `/clear` |
| 反复纠错不如重来 | 纠正两次以上还不对 | `/clear` 并写更好的初始提示 |
| CLAUDE.md 太长 | 规则被忽略 | 无情修剪到 200 行以内 |
| 不提供验证手段 | 输出看起来对但实际不工作 | 每次给出测试/脚本/截图 |
| 无边界的调查任务 | Context 被几百个文件塞满 | 限定范围或用 subagents |
| 信任但不验证 | 边界情况处理缺失 | 始终提供验证方式 |

---

## 七、支持的环境

| 环境 | 特点 |
|------|------|
| **终端 CLI** | 功能最完整，直接操作文件系统 |
| **VS Code 扩展** | 内联 diff、@-引用、计划审查、对话历史 |
| **JetBrains 插件** | 支持 IntelliJ、PyCharm、WebStorm |
| **桌面应用** | 可视化 diff、并行会话、定时任务、远程控制 |
| **Web 版** | 浏览器内运行，无需本地安装，支持长任务 |
| **GitHub Actions** | 自动化 PR 审查和 Issue 分类 |
| **Slack 集成** | `@Claude` 接收错误报告，自动返回 PR |
| **Chrome 扩展** | 调试实时 Web 应用，视觉验证 UI |

**关键点**：所有环境共享同一套 Claude Code 引擎，`CLAUDE.md`、MCP 配置、Settings 全部通用。

---

## 八、快速命令参考

### 斜杠命令

| 命令 | 功能 |
|------|------|
| `/init` | 根据项目自动生成 CLAUDE.md |
| `/help` | 查看帮助 |
| `/clear` | 清除对话历史，重置 context |
| `/compact` | 压缩对话历史，释放 context |
| `/memory` | 查看/编辑记忆文件 |
| `/hooks` | 查看/配置 hooks |
| `/agents` | 查看/创建子代理 |
| `/resume` | 打开会话选择器 |
| `/rename <name>` | 重命名当前会话 |
| `/rewind` | 回退到之前状态 |
| `/permissions` | 管理工具权限 |
| `/effort` | 调整思考深度 |
| `/schedule` | 创建定期任务 |
| `/btw <question>` | 侧问，答案不进 context |

### 键盘快捷键

| 快捷键 | 功能 |
|--------|------|
| `Shift+Tab` | 切换权限模式（Normal / Auto-Accept / Plan） |
| `Esc` | 中断 Claude |
| `Esc+Esc` | 打开 Rewind 菜单 |
| `Ctrl+G` | 在编辑器中打开当前计划 |
| `Ctrl+O` | 切换详细模式（查看 Claude 思考过程） |
| `Option+T` / `Alt+T` | 切换 Thinking Mode |

---

## 九、总结

Claude Code 代表了 AI 辅助编程的范式转变：

- **从"生成代码片段"到"完成工程任务"**
- **从"人驱动 AI"到"人监督 AI 自主执行"**
- **从"对话式"到"代理式（Agentic）"**

**最高价值的五个习惯：**

1. 🗺️ **先探索，再规划，最后编码** —— Plan Mode 三步走，避免解决错误的问题
2. ✅ **给 Claude 验证手段** —— 测试、截图、脚本，让 Claude 能自检
3. 🧹 **积极管理 context** —— 不相关任务之间 `/clear`，保持 context 干净
4. 📝 **写好 CLAUDE.md** —— 短而精准，用 `/init` 起步，定期修剪
5. 🤖 **用子代理做调查** —— 保护主对话的宝贵 context，让子代理探索代码库

跟着用、边用边学。Claude Code 的真正威力在实战中才能感受到。

---

## 参考资料

- [Claude Code 官方中文文档](https://code.claude.com/docs/zh-CN/overview)
- [Claude Code 最佳实践](https://code.claude.com/docs/zh-CN/best-practices)
- [Claude Code 常见工作流](https://code.claude.com/docs/zh-CN/common-workflows)
- [Claude Code 记忆系统](https://code.claude.com/docs/zh-CN/memory)
- [菜鸟教程 - Claude Code 教程](https://www.runoob.com/claude-code/claude-code-tutorial.html)
- 字节跳动 Claude Code 中文使用手册（微信公众号广泛流传版）
- [GitHub: claude-code-chinese/claude-code-guide](https://github.com/claude-code-chinese/claude-code-guide)
