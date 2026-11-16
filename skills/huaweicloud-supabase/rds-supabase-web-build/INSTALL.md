# rds-supabase-web-build 安装（AI Agent 一键安装）

面向 AI Agent 的安装指导。用户对 Agent 说：

> 按照 https://github.com/huaweicloud/rds-supabase-fullstack/blob/main/skills/huaweicloud-supabase/rds-supabase-web-build/INSTALL.md ，安装 rds-supabase-web-build 技能及其**全部配套技能**；装完告诉我如何触发建站。

Agent 按本文四节执行。安装范围是 **`skills/huaweicloud-supabase/` 下全部七个技能（必须一次装齐，缺一不可、不得跳过）**——但不含任何 MCP、凭据与云资源；MCP 与凭据在九步工作流内按需动态安装（见下表）。

## 一、安装范围

| 项 | 何时 | 来源 |
|---|---|---|
| **技能全家桶——`skills/huaweicloud-supabase/` 下七个目录必须一次装齐，缺一不可、不得跳过** | 现在，一次性 | 本 GitHub 源码仓 |
| 管理面 MCP（53 工具） | 工作流步骤三动态启动 | 本仓 `server/`（不在技能包内） |
| 数据面 MCP（38 工具） | 工作流步骤四动态安装 | 同上；依赖步骤三交付的实例凭据 |
| 凭据 / Region / 接入点 / PROJECT_ID | 工作流步骤一 | 项目内 `.hwsupabase/`（项目级隔离） |

**配套技能清单（与 web-build 同批安装，缺一即安装失败，不降级、不跳过）**：

| 技能目录 | 角色（参与时机） |
|---|---|
| `rds-supabase-web-build` | 顶层编排：九步状态机（本技能） |
| `rds-supabase-mgr-mcp` | 管理面场景编排（步骤三） |
| `rds-supabase-mcp` | 数据面安装 · init.sql 规范与五步部署（步骤四起） |
| `rds-supabase-postgres-best-practices` | SQL 质量强制门（步骤五） |
| `rds-supabase-usage` | SDK 用法强制门（步骤五/六） |
| `rds-supabase-frontend` | 前端构建与 OBS 托管（步骤三/八） |
| `rds-supabase-function-graph` | 云函数扩展（复杂业务逻辑按需） |

**红线**：安装校验发现任何配套技能缺失 → 补装后再完成报告；不得提示"部分安装可用"——编排路由依赖全部七个目录就位。

前置：Agent 支持 Agent Skills 标准；网络可达 GitHub（通道受限时经环境探测果断走 ZIP 直下，见第 1 步）。

## 二、安装位置选择（必须交互，默认项目级）

安装前 Agent **必须**把下表展示给用户、等用户明确选择后才落盘——不许静默安装到任何位置。**默认选项是项目级**（回车/说"默认"即选它）。选用户级或系统级时，Agent 必须复述对应的风险提示并获得用户再次确认。本技能是编排者，安装位置同时决定六个配套技能的落位——**七技能必须同层级一次装齐**。

| 选项 | 目录（按宿主解析） | 生效范围与后果 |
|---|---|---|
| **① 项目级（默认，推荐）** | CodeArts：`<项目根>/.codeartsdoer/skills/`；opencode：`<项目根>/.opencode/skills/`；Claude Code：`<项目根>/.claude/skills/`；其余宿主：该宿主的项目级技能机制 | 仅本项目可见。九步状态机与路由目标在同一项目内一致；凭据与 MCP 配置（恒为项目级）同界 |
| ② 用户级 | CodeArts：`~/.codeartsdoer/skills/`；opencode：`~/.config/opencode/skills/`；Claude Code：`~/.claude/skills/`；其余宿主：宿主个人级技能目录 | 本机所有项目可见。任何项目说"建个网站"都会触发本技能；升级影响全部项目 |
| ③ 系统级 | 宿主的系统级/内置技能目录（若存在） | 本机所有用户、所有项目可见。影响面最大，一般仅管理员统一预装时使用 |

交互示例：

```
请选择技能安装位置（默认 ①）：
① 项目级（推荐）：<项目根>/.claude/skills/     —— 仅本项目生效
② 用户级：        ~/.claude/skills/            —— 本机全部项目生效，升级影响所有项目
③ 系统级：        <宿主系统级技能目录>          —— 全机所有用户生效，影响面最大
```

风险提示（用户选 ②③ 时必须复述）：
- 用户级/系统级会把技能暴露给无关项目与无关用户，本项目后续升级、卸载都会波及它们
- CodeArts 的 `~/.codeartsdoer/skills` 与项目级 `<项目根>/.codeartsdoer/skills` 同名不同根，极易装错——选 ② 时逐字核对完整路径
- 凭据与 MCP 配置始终只在项目级（本技能红线），装到用户级/系统级不会改变这一点

## 三、三步安装

### 第 1 步 · 安装技能文件（先探测后选择：A/B/C）

**前置：环境探测与方法选择（一次探测定通道）**——部分用户环境对 git 有公网限制（实测场景），先按序执行两项探测（各一次、失败不重试），按结果直接选定方式：

```bash
# 探测①：方式 A 前置——Node.js ≥ 22.20（npx skills add 的运行条件）
node --version 2>/dev/null
# 探测②：方式 B 前置——git 在且 GitHub 直连可达（git 公网受限的环境此步即失败）
git ls-remote https://github.com/huaweicloud/rds-supabase-fullstack.git HEAD
```

| 探测结果（一次即定） | 直接选定 |
|---|---|
| ① 输出版本 ≥ v22.20 | **方式 A** |
| ① 不过（无 Node 或版本低）；② 返回 HEAD 引用 | **方式 B** |
| ①② 都不过——无 git、`ls-remote` 失败或超时（git 公网受限实测场景） | **方式 C（果断直切，不再回头试 A/B）** |

执行纪律：选定后直接执行；仅当**执行本身**失败时按 A→B→C 顺降一次，并跳过探测已判不可用的方式，同一方式不重复第二次。

**方式 A**（`npx skills add`，主路径，推荐）：标准 Agent Skills 生态 CLI（Vercel 开源，支持 OpenCode、Claude Code 等 75+ 宿主）直接从本仓 GitHub 源安装；前置 Node.js ≥ 22.20。重复 `--skill` 一次装齐七个技能（实测支持）——**少装任何一个，编排路由即失败**。

```bash
npx skills add huaweicloud/rds-supabase-fullstack \
  --skill rds-supabase-web-build --skill rds-supabase-mgr-mcp --skill rds-supabase-mcp \
  --skill rds-supabase-usage --skill rds-supabase-frontend \
  --skill rds-supabase-postgres-best-practices --skill rds-supabase-function-graph \
  -a <宿主> -y
```

`-a <宿主>` 取 `opencode` / `claude-code` / `cursor` 等（省略则交互选择本机已检测的宿主）；`-g` 装用户级（默认项目级）。安装即生成 `skills-lock.json` 锁定来源 commit；更新 `npx skills update`，卸载 `npx skills remove`。失败或行为异常时切方式 B，不反复重试。

**方式 B**（git 克隆复制，备选——npx 失败、无 Node.js ≥22.20 或需精确控制复制内容时）：

```bash
TMP=$(mktemp -d)   # 克隆落唯一临时目录，不污染项目目录与家目录
git clone https://github.com/huaweicloud/rds-supabase-fullstack "$TMP/repo"
cp -r "$TMP/repo/skills/huaweicloud-supabase/"* <项目技能目录>/   # 七技能一次装齐
rm -rf "$TMP"     # 复制完成即清理
```

**方式 C**（ZIP 直下自动解压，HTTPS 443 通道——探测②不通（git 公网受限）或 A/B 执行失败即果断直切，不重试）：**下载与解压固定落当前工作区项目根目录，禁止就此询问用户**（安装全程仅第二节的安装位置需用户交互）。在项目根执行：

```bash
curl -L --fail --max-time 120 -o rds-supabase-skills.zip \
  https://github.com/huaweicloud/rds-supabase-fullstack/archive/refs/heads/main.zip
unzip -q rds-supabase-skills.zip   # 解压出 rds-supabase-fullstack-main/
cp -r rds-supabase-fullstack-main/skills/huaweicloud-supabase/* <项目技能目录>/   # 七技能一次装齐
rm -rf rds-supabase-skills.zip rds-supabase-fullstack-main/   # 复制完成即清理，项目零残留
```

`<项目技能目录>` 按第二节用户已选位置由 Agent 自行解析（项目级即宿主项目技能目录），同样不询问。浏览器直接下载该 ZIP URL 亦可——**落点固定为项目根目录**，不选择保存位置。ZIP 走 HTTPS 443 通道，与 git 传输不同路，通常不受 git 公网限制影响。ZIP 归档属本仓官方源；版本 pin 等价形式 `.../archive/<commit>.zip`（解压目录名相应变化）。

### 第 2 步 · 校验

校验两项：

1. **七技能齐装**——`<项目技能目录>/` 下第一节清单所列七个技能目录全部存在且各含 `SKILL.md`；缺任何一项 → 回第 1 步补装，不得以"部分安装"收尾。
2. 本技能目录内含 `README.md`、`INSTALL.md`、`showcase.md`（演示材料，不参与技能运行）、`assets/`、`references/`、`scripts/`、`tests/`。

### 第 3 步 · 完成报告

向用户汇报四项：安装路径与七个技能清单；触发语句示例（如"帮我建一个博客网站"）；约定说明——MCP 与凭据不在安装阶段出现，首次建站时技能从步骤一环境检查开始逐项处理；演示材料入口（`showcase.md`——建站模式对比展示，与技能运行无关）。

## 四、更新与卸载

- **更新**：`git pull` 后重新复制（重复第 1 步，七技能同批更新）
- **卸载**：删除项目级技能目录中七个技能目录（配套技能系独立安装复用的可保留并在报告中注明）；工作流曾配置 MCP 的，另移除项目级 MCP 配置中对应条目
