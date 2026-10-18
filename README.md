# AI Banking Agent

一个基于自然语言对话的智能银行助手（Agent）系统：理解用户的金融意图，自主规划并执行银行业务操作，可通过 **Web/APP/IM 渠道** 与 Agent 联通。

系统采用 **Python + FastAPI + LangGraph** 构建，LLM 可插拔（OpenAI 兼容接口），并内置**离线规则引擎**作为无 API Key 时的回退，保证开箱即用、可离线演示。

## 核心能力

| 场景 | 能力 | 示例指令 |
| --- | --- | --- |
| 智能转账 | 按姓名/手机号/备注转账、定时转账、AA 收款拆分 | `转 500 元给张三，备注聚餐` |
| 账单分析 | 消费分类统计、异常交易识别、月度/年度账单报告 | `分析我上个月的账单` |
| 理财操作 | 风险评估、产品推荐与对比、一键申购/赎回 | `推荐一款稳健理财` |
| 卡片管理 | 办卡、额度调整、交易限制/解锁、挂失 | `帮我挂失尾号 8888 的卡` |
| 订阅/代扣 | 自动识别订阅扣费、续费提醒、一键取消 | `取消腾讯视频订阅` |
| 跨场景联动 | 检测爱人生日 → 锁定资金 → 生日前订购鲜花蛋糕 | `检测我爱人生日，锁定1000元` |

## 架构

```
用户(Web/IM/APP)
      │  REST /api/chat  或  WebSocket /ws/chat
      ▼
FastAPI 渠道层 (src/ai_banking/api)
      │
      ▼
LangGraph Agent (src/ai_banking/agent)
   understand ──► plan ──► act ──► respond
   (意图识别)   (路由)  (执行工具) (生成回复)
      │                       │
      ▼                       ▼
可插拔 LLM 层            工具注册表 ToolRegistry
(OpenAI 兼容 / 规则回退)     ├─ scenario_transfer
                            ├─ scenario_bill
                            ├─ scenario_wealth
                            ├─ scenario_card
                            ├─ scenario_subscription
                            └─ scenario_cross
      │                       │
      ▼                       ▼
领域共享层 (domain/accounts, domain/scheduler)
      │
      ▼
SQLite (SQLAlchemy ORM, core/models)
```

- **Agent 状态机**（`agent/graph.py`）：`understand → plan → act → respond` 四节点。
- **意图识别**（`llm/`）：优先调用 OpenAI 兼容 LLM（JSON 模式）；失败或无 Key 时回退到离线规则引擎。
- **确定性路由**（`agent/router.py`）：意图 + 实体 → 规范工具名，是各场景模块的接口契约。
- **安全护栏**（`safety/guardrails.py`）：高风险/大额操作二次确认，PII（手机号/卡号/姓名）脱敏。
- **审计**（`safety/audit.py`）：每次工具调用写入审计日志。
- **后台调度**（`domain/scheduler.py`）：轮询 `scheduled_jobs` 表，驱动定时转账、生日检测、续费提醒。

## 快速开始

环境要求：Python 3.10+。

```powershell
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt

# 2.（可选）配置 LLM，复制 .env.example 为 .env 并填写
#    LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
#    不配置也可运行：自动回退到离线规则引擎

# 3. 初始化演示数据
$env:PYTHONPATH="f:\AI_BANKING\src"
.\.venv\Scripts\python.exe -m ai_banking.scripts.seed

# 4. 启动服务
.\.venv\Scripts\python.exe -m uvicorn ai_banking.api.main:app --host 127.0.0.1 --port 8000

# 5. 浏览器打开 http://127.0.0.1:8000 即可使用 Web 对话界面
```

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查（工具数、LLM 配置状态） |
| GET | `/api/tools` | 列出已注册工具及其 schema |
| POST | `/api/chat` | 对话：`{user_id, session_id?, message}` → `{session_id, response, intent, tool_used, data, requires_confirmation}` |
| WS | `/ws/chat` | 同上，WebSocket 长连接 |
| GET | `/` | Web 聊天界面（静态文件） |

## 项目结构

```
f:\AI_BANKING
├── requirements.txt
├── .env.example
├── README.md
├── tests/
│   └── test_e2e.py                 # 6 场景端到端测试
└── src/ai_banking/
    ├── config.py                   # 配置（dotenv）
    ├── api/main.py                 # FastAPI 渠道层（REST + WS + 静态）
    ├── agent/
    │   ├── graph.py                # LangGraph 状态机
    │   ├── router.py               # 意图 → 工具路由契约
    │   ├── state.py / memory.py    # 状态与会话记忆
    │   └── tools/                  # 6 个场景工具模块
    ├── llm/                        # 可插拔 LLM 层（openai_provider / rule_fallback）
    ├── domain/                     # accounts（转账/锁定/流水）、scheduler（后台调度）
    ├── safety/                     # guardrails（风险/脱敏）、audit（审计）
    ├── core/                       # models（14 张表）、database、tooling、errors、logging
    ├── schemas/                    # 共享 Pydantic 契约（Intent/ToolResult）
    └── scripts/seed.py             # 演示数据
```

## 二次确认机制

高风险或大额操作（大额转账、挂失、赎回、取消订阅、额度调整等）会返回 `requires_confirmation=true`，Agent 在内存中暂存待确认操作；用户回复“确认”后以 `confirmed=true` 重新执行，回复“取消”则放弃。

## 测试

```powershell
$env:PYTHONPATH="f:\AI_BANKING\src"
.\.venv\Scripts\python.exe -m pytest tests\test_e2e.py -v
```
