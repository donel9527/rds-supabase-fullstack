# rds-supabase-function-graph 安装（AI Agent 一键安装）

安装范围**仅本技能**——技能文档、样板与验证门脚本；不安装、不配置 MCP 服务器、凭据与云资源。云操作全部经 KooCLI（前置条件见 README"前置条件"，在技能触发后的步骤一核对，缺失则提醒安装并停止）。

将下面这句话发送给你的 AI Agent：

> 按照 https://github.com/huaweicloud/rds-supabase-fullstack/blob/main/skills/huaweicloud-supabase/rds-supabase-function-graph/INSTALL.md 安装 rds-supabase-function-graph 技能；装完报告安装路径。

## 一、安装位置选择（必须交互，默认项目级）

前置：Agent 支持 Agent Skills 标准；网络可达 GitHub（通道受限时经环境探测果断走 ZIP 直下，见安装方式节）。

安装前 Agent **必须**把下表展示给用户、等用户明确选择后才执行安装——不得静默安装到任何位置。**默认选项是项目级**（回车或输入“默认”即选择项目级）。选用户级或系统级时，Agent 必须复述对应的风险提示并获得用户再次确认。

| 选项 | 目录（按宿主解析） | 生效范围与后果 |
|---|---|---|
| **① 项目级（默认，推荐）** | Claude Code：`<项目根>/.claude/skills/`；opencode：`<项目根>/.opencode/skills/`；CodeArts：`<项目根>/.codeartsdoer/skills/`；其余宿主：该宿主的项目级技能机制 | 仅本项目可见。技能版本随项目走，团队成员各自安装后行为一致；不污染其他项目 |
| ② 用户级 | Claude Code：`~/.claude/skills/`；opencode：`~/.config/opencode/skills/`；CodeArts：`~/.codeartsdoer/skills/`；其余宿主：宿主个人级技能目录 | 本机所有项目可见。你本机任何项目的对话都可能触发本技能；技能升级影响全部项目 |
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

## 二、安装方式（先探测后选择：A/B/C）

### 前置：环境探测与方法选择（一次探测定通道）

部分用户环境对 git 有公网限制（实测场景），安装前先按序执行两项探测——各一次、失败不重试——按结果直接选定方式：

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

执行纪律：选定后直接执行；仅当**执行本身**失败时按 A→B→C 顺降一次，并跳过探测已判不可用的方式（如 A 执行失败而探测②曾失败 → 跳过 B 直用 C），同一方式不重复第二次。

### 方式 A：`npx skills add`（主路径，推荐）

标准 Agent Skills 生态 CLI（Vercel 开源，支持 OpenCode、Claude Code 等 75+ 宿主）直接从本仓 GitHub 源安装；前置 Node.js ≥ 22.20。

```bash
npx skills add huaweicloud/rds-supabase-fullstack --skill rds-supabase-function-graph -a <宿主> -y
```

- `--skill rds-supabase-function-graph`：只装本技能（省略则交互列出本仓全部 8 个技能供勾选）
- `-a <宿主>`：`opencode` / `claude-code` / `cursor` 等（省略则交互选择本机已检测的宿主）
- `-g`：装到用户级（默认项目级——与本文件第一节的位置选择对应；CLI 默认落 `.agents/skills/`，宿主按其发现规则识别）
- 安装即生成 `skills-lock.json` 锁定来源 commit；更新用 `npx skills update`，卸载用 `npx skills remove`
- 失败或行为异常时切方式 B，不反复重试

### 方式 B：git 克隆复制（备选——npx 失败、无 Node.js ≥22.20 或需精确控制复制内容时）

```bash
TMP=$(mktemp -d)   # 克隆落唯一临时目录，不污染项目目录与家目录
git clone https://github.com/huaweicloud/rds-supabase-fullstack "$TMP/repo"
cp -r "$TMP/repo/skills/huaweicloud-supabase/rds-supabase-function-graph" <项目技能目录>/
rm -rf "$TMP"     # 复制完成即清理
```

### 方式 C：ZIP 直下自动解压（HTTPS 443 通道——git 公网受限或 A/B 执行失败即果断直切，不重试）

**下载与解压固定落当前工作区项目根目录，禁止就此询问用户**（安装全程仅安装位置需用户交互）。在项目根执行：

```bash
curl -L --fail --max-time 120 -o rds-supabase-skills.zip \
  https://github.com/huaweicloud/rds-supabase-fullstack/archive/refs/heads/main.zip
unzip -q rds-supabase-skills.zip   # 解压出 rds-supabase-fullstack-main/
cp -r rds-supabase-fullstack-main/skills/huaweicloud-supabase/rds-supabase-function-graph <项目技能目录>/
rm -rf rds-supabase-skills.zip rds-supabase-fullstack-main/   # 复制完成即清理，项目零残留
```

`<项目技能目录>` 按第二节用户已选位置由 Agent 自行解析（项目级即宿主项目技能目录），同样不询问。浏览器直接下载该 ZIP URL 亦可——**落点固定为项目根目录**，不选择保存位置。ZIP 走 HTTPS 443 通道，与 git 传输不同路，通常不受 git 公网限制影响。ZIP 归档属本仓官方源，为无 Node.js 环境时的备选。

## 三、校验与完成报告

- 校验：技能目录内含 `SKILL.md`、`README.md`、`INSTALL.md`、`references/` 五个参考文档、`template/` 样板、`scripts/fgs-gate.py`、`tests/`
- 向用户报告：安装位置（层级 + 完整路径，须与交互选择一致）；触发语示例（如"给博客加一个交易通知云函数，需要幂等防重放"）；前置提示——首次使用前需 KooCLI 已安装认证、有可用 RDS Supabase 应用与 OBS 桶

## 四、更新与卸载

- **更新**：方式 A 安装的用 `npx skills update`（按 skills-lock.json 锁定的 commit 前滚）；git 复制的 `git pull` 后重新复制（重复方式 B；版本 pin 等价形式 `.../archive/<commit>.zip`）
- **卸载**：删除项目级技能目录中本技能；已部署的云函数属云端资源，卸载技能不影响，按 SKILL.md 下线规程另行处理
