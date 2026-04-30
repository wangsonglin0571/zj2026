# 每日信息简报自动化方案复盘

这份文档整理自 `/Users/wangsonglin/tech-digest` 项目，用于给其他项目借鉴：如何把一组信息源每天自动抓取、筛选、摘要，并推送给订阅者。

## 一句话思路

用 RSS 做低成本采集，用大模型做筛选和摘要，用本地定时任务稳定运行，用订阅式推送工具完成交付。

核心不是“做一个新闻 App”，而是搭一条足够稳定的自动化流水线：

```text
信息源
  → 抓取与健康检查
  → 候选排序
  → 大模型筛选摘要
  → Markdown 格式化
  → 本地归档
  → 订阅推送
  → 日志排错
```

## 当前项目形态

目标：Mac mini 每天 08:00 自动生成中文科技简报，并推送到微信。

技术选择：

| 模块 | 选择 | 借鉴点 |
|------|------|--------|
| 语言 | Python | 适合轻量脚本和本地自动化 |
| RSS 解析 | feedparser | 成熟，足够处理 RSS/Atom |
| HTTP | httpx | 支持超时、重定向、状态码检查 |
| 摘要 | DeepSeek | 用 OpenAI 兼容接口，替换模型成本低 |
| 推送 | WxPusher Topic | 适合多人订阅，Topic 模型清晰 |
| 补源 | RSSHub | 用 Docker 本地跑，补充无 RSS 的中文源 |
| 调度 | macOS launchd | 本地 Mac mini 上比额外调度系统更简单稳定 |
| 归档 | Markdown 文件 | 不引入数据库，方便查看和备份 |

## 信息源策略

最终固定 8 个源，分成主干和中文补充。

主干 5 个：

- Hacker News
- Techmeme
- InfoQ
- Ars Technica
- V2EX

中文补充 3 个：

- 36氪
- 虎嗅
- 少数派

设计原则：

- 主干源负责全球技术趋势和英文技术圈信号。
- 中文源负责本地化语境、产业消息和中文社区反馈。
- 每源只取前 5 条，避免某个源淹没整体候选池。
- 给源设置权重，用于候选预排序。
- 信息源必须可健康检查，不要等到推送失败才发现 RSS 失效。

## 数据流设计

当前流程：

```text
8 个 RSS 源，每源取 5 条，共约 40 条
  → 按 weight × freshness 预排序
  → 取 Top 20 作为候选
  → DeepSeek 从候选中选 Top 10 并生成中文摘要
  → 格式化为 Markdown
  → 先保存 digest_YYYYMMDD.md
  → 再推送到 WxPusher Topic
```

关键点：

- 先保存本地文件，再推送。推送失败也不丢内容。
- 每个 RSS 源独立 try/except。单源失败不影响整体。
- 大模型只处理 Top 20 候选，控制成本和输出稳定性。
- 输出要求严格 JSON，解析失败时记录原始返回，便于排查。

## 推送模型

最终选择 WxPusher Topic。

原因：

- 比个人单发更适合多人订阅。
- 订阅者通过 Topic 加入，后续推送不用维护每个人的 UID。
- UID 单发仍可作为测试手段，用来判断用户是否已正确关注应用。

需要注意：

- 用户只关注应用，不一定订阅 Topic。
- Topic 推送成功只表示 WxPusher 创建了发送任务。
- 若某个用户收不到，需要确认它是否同时完成：
  - 关注应用
  - 订阅对应 Topic
- 代码需要检查 WxPusher 返回的每个目标结果，不能只看顶层 `code=1000`。

## 调度选择

原先考虑过 OpenClaw，最终改用 macOS `launchd`。

理由：

- 当前任务只需要每天定时执行一次。
- 运行环境是固定 Mac mini。
- `launchd` 是 macOS 原生调度，少一个外部依赖。
- 可用 `launchctl kickstart` 手动触发，调试方便。

典型命令：

```bash
launchctl print gui/$(id -u)/com.wangsonglin.techdigest
launchctl kickstart -k gui/$(id -u)/com.wangsonglin.techdigest
tail -f /Users/wangsonglin/tech-digest/logs/run.log
```

## 目录结构

这个结构适合小型自动化项目复用：

```text
project/
├── main.py                 # 入口，只做流程编排
├── config.py               # 配置、信息源、环境变量校验
├── fetcher.py              # 抓取、RSS 解析、源健康检查
├── summarizer.py           # 模型调用、JSON 解析、Markdown 格式化
├── pusher.py               # 推送适配器
├── requirements.txt
├── .env.example
├── docker-compose.yml      # RSSHub 或其他本地依赖
├── run.sh                  # 给 launchd 调用
├── xxx.plist               # launchd 配置
└── logs/
```

## 命令设计

除了默认运行，建议一定保留几个维护命令：

```bash
# 完整生成并推送
python3 main.py

# 只推送已有文件，不重新抓取和摘要
python3 main.py --push-only

# 推送指定 Markdown 文件
python3 main.py --push-only --file digest_20260426.md

# 检查所有信息源是否可用
python3 main.py --check-sources
```

这些命令让日常排查简单很多：

- `--check-sources` 判断是不是 RSS 源坏了。
- `--push-only` 判断是不是推送链路坏了。
- 完整 `main.py` 判断整条链路是否正常。

## 可迁移到 zj2026 的地方

如果 `zj2026` 也需要做定时数据更新或信息推送，可以借鉴这些模式：

- 把外部数据源集中放在 `config.py`，不要散落在业务代码里。
- 给数据源增加健康检查命令。
- 本地生成结果文件后再发布，避免发布失败导致数据丢失。
- 把“生成”和“发布”拆开，支持只发布已有结果。
- 日志分为正常运行日志和错误日志。
- 对外部 API 返回做细粒度检查，不只看 HTTP 200。
- 本地 Mac 定时任务优先用 `launchd`，除非确实需要跨机器编排。

## 最重要的经验

1. 先把链路跑通，再追求架构漂亮。
2. 每一步都要能单独验证：源、模型、推送、调度。
3. 推送系统的“API 成功”不等于“用户收到”，要设计可定位的测试路径。
4. 文档里的技术决策要跟实际代码同步，否则后续维护很容易被旧方案带偏。
5. 对小型个人自动化来说，Markdown 归档加日志，比数据库更轻、更可靠。
