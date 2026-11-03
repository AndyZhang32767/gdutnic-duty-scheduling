# GDUTNIC 排班签到

网络服务协会的值班排班与签到系统。普通成员用姓名和密码登录，查看自己的排班并签到；管理员在管理端维护每日/每周/特殊排班、账号权限、外勤登记与考勤统计。界面保留 Material You 风格。

> 旧版的 Wiki 对话助手（MCP、企业 OAuth、QQ 机器人）代码仍保留在 `server/` 中，但当前界面不再提供入口，默认不启用。

## 项目结构

```text
gdutnic-outline-assistant/
├── server/                 后端（FastAPI）
│   ├── app.py              应用入口、路由、会话与权限校验
│   ├── db.py               MySQL/SQLite 连接、事务与建表升级
│   ├── schedule_store.py   班次、签到与连班自动签到
│   ├── weekly_store.py     每周模板、CSV 名单与按日期生成
│   ├── overview.py         月度统计、周历与手工考勤改判
│   ├── field_duty.py       外勤登记与月度看板
│   ├── member_store.py     普通账号的创建、鉴权与改密
│   ├── admin_store.py      管理员路径与控制台配置缓存
│   ├── permissions.py      权限树、叶子集合与旧数据迁移
│   ├── duty_settings.py    提前打卡 / 迟到 / 旷班分钟数
│   ├── security.py         登录限流、会话时长与安全响应头
│   ├── migrate_mysql.py    SQLite → MySQL 迁移
│   ├── provision_members.py 补齐名单账号
│   ├── grant_admin.py      给账号补授全部权限
│   └── chat.py / qq_bot.py / mcp_client.py / oauth.py  旧版 Wiki 助手（未启用）
├── web/                    前端静态页
│   ├── index.html          成员端：登录、当日排班、外勤登记
│   ├── admin.html          管理端：概览、排班、用户、外勤、设置
│   ├── schedule.js         页面切换、签到表单、班次编辑
│   ├── overview.js         月度统计、时间轴、周历、详情弹窗
│   ├── weekly.js / weekly-import.js   每周模板与 CSV 导入
│   ├── special.js          特殊排班
│   ├── members.js          账号列表、搜索与权限树
│   ├── field-admin.js      外勤看板
│   ├── status-editor.js    手工改判考勤/外勤的通用弹窗
│   ├── field-duty.js       成员端外勤登记
│   ├── shift-timeline.js   值班时间轴（含几何测试）
│   ├── checkin-window.js   签到窗口判定
│   ├── settings.js         其他设置
│   └── styles.css / schedule.css  Material You 样式
├── sql/mysql_schema.sql    MySQL 建表语句
├── tests/                  Python 与 Node 测试
├── icon/                   站点图标
├── data/                   运行时数据（不提交）
│   ├── session_secret.txt  会话签名密钥
│   ├── weekly_roster.json  每周名单种子
│   └── imports/            排班表与 CSV 模板
├── start.sh / start.bat    启动脚本
└── compose.yaml            本地 MySQL 8.4
```

## 项目各部分使用方法

### 启动与首次配置

```bash
cp .env.example .env          # 填写 MYSQL_* 等参数
docker compose up -d mysql    # 使用本地 Docker MySQL
./start.sh                    # Windows 用 start.bat
```

启动日志会打印管理员地址（形如 `http://127.0.0.1:50025/a8clrf3j`）。首次打开该地址会创建管理员，首个管理员自动获得全部权限。

### 成员端（`/`）

1. 用姓名和密码登录，默认初始密码 `gg2017`。
2. 页面只显示本人在当天的班次；在班次开始前「提前打卡」分钟内按钮变为可点。
3. 点击签到后记录到岗时间；若下一班与本班首尾相接（1→2、3→4），会自动一并签到。
4. 左侧「外勤管理」中点击按钮登记本月外勤，成功后按钮固定为「登记完成」。
5. 左侧底部可修改密码；会话 4 小时后过期。

### 管理端概览

- 右上角选择月份，查看出勤率、迟到数、旷班数。
- 时间轴显示当前值班与人员姓名；下方周历按班次行横向对齐。
- 点击本周卡片打开详情，再点击某个人名可改判考勤状态。

### 每日 / 每周 / 特殊排班

- **每日排班**：按日期查看，点击卡片编辑或删除；删除会连同签到记录一起删除。
- **每周排班**：填写四个班次的时间与周一至周日人员，保存后核对勾选；用「下载 CSV 模板」与「一键导入」批量填人。
- **生成排班**：选择截止日期，按星期从今天生成到该日，已存在或冲突的班次会跳过。
- **特殊排班**：新增一次性班次，可在未来特殊排班列表中编辑或删除。
- **清除所有排班**：需输入确认语，删除全部班次与签到，保留模板和账号。

### 用户管理

- 顶部搜索框按姓名即时筛选。
- 卡片右侧可更改权限、更改密码、重置密码、停用/启用、删除账号。
- 「更改权限」弹窗为可折叠树，勾选父级会展开并选中全部子项。

### 外勤管理

- 选择月份查看参与情况，点击人员卡片切换已参加/未参加。
- 管理员修改的条目会显示「管理员修改」。

### 其他设置

- 设置提前打卡、迟到、旷班分钟数；旷班时间必须大于迟到时间。

### 维护命令

```bash
.venv/bin/python -m server.provision_members     # 补齐名单账号
.venv/bin/python -m server.grant_admin <账号名>  # 补授全部权限
.venv/bin/python -m server.migrate_mysql --source data/app.sqlite  # 旧库迁移
```

## 权限模型

每个账号都带一张权限表，管理员只是持有管理权限的账号。

| 权限 | 作用 |
| --- | --- |
| 用户界面 | 登录成员页，查看本人排班并签到 |
| 更改排班 | 每日/每周/特殊排班与其他设置 |
| 操作账号 | 重置密码、启用/停用账号 |
| 添加/删除账号 | 新建、删除账号 |
| 更改权限 | 为他人分配权限；持有权限的账号受保护 |
| 外勤管理 | 外勤统计与手动登记 |

规则：

- 拥有任意一项管理权限即可进入管理端并查看概览。
- 没有「更改权限」的人不能删除、停用、重置或更改**持有管理权限**的账号；纯值班账号不受此限制。
- 更改密码只能由账号本人或持有「更改权限」的人操作。
- 首次在控制台地址注册的账号自动获得全部权限。
- 权限被收回后，该账号的管理端会话立即失效。

## 环境要求

- Python 3.10+（建议 3.12）
- MySQL 8.4（默认后端）；SQLite 仅用于迁移兼容与隔离测试

## 配置

复制 `.env.example` 为 `.env` 并填写，环境变量优先于 `.env`：

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `DB_BACKEND` | `mysql` 或 `sqlite` | `mysql` |
| `MYSQL_HOST` | 数据库地址 | `127.0.0.1` |
| `MYSQL_PORT` | 数据库端口 | `3306`（`.env.example` 中为 Docker 的 `3307`） |
| `MYSQL_DATABASE` | 数据库名 | `gdutnic` |
| `MYSQL_USER` / `MYSQL_PASSWORD` | 应用账号 | — |
| `MYSQL_ROOT_PASSWORD` | 仅由 `compose.yaml` 的本地 MySQL 容器读取，应用本身不用 | — |
| `MYSQL_SSL_CA` | 远程 TLS 证书路径（可选） | — |
| `SESSION_SECRET` | 会话签名密钥（可选，缺省写入 `data/session_secret.txt`） | — |
| `SESSION_HTTPS_ONLY` | 设为 `1/true/yes` 时 Cookie 仅经 HTTPS 发送并启用 HSTS | 关闭 |

请事先创建数据库并授予应用账号建表与读写权限；应用启动时会自动建表并补齐新增字段，不会覆盖旧数据。

## 启动

使用本地 Docker MySQL：

```bash
docker compose up -d mysql
./start.sh
```

Windows 使用 `start.bat`。启动脚本会创建项目内 `.venv`、安装依赖（默认 PyPI 失败时自动尝试国内镜像），然后监听 `0.0.0.0:50025`。

手动启动：

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn server.app:app --host 0.0.0.0 --port 50025
```

启动后控制台会打印管理员地址（形如 `http://127.0.0.1:50025/a8clrf3j`）。首次打开站点会跳转到该地址创建管理员；之后的账号在「用户管理」中添加。

启动时还会为每周名单及已排班人员补齐缺失账号，也可单独执行：

```bash
.venv/bin/python -m server.provision_members
```

给指定账号补授全部权限（管理员恢复用）：

```bash
.venv/bin/python -m server.grant_admin <账号名>
```

## 数据与备份

- **业务数据**保存在 MySQL（Docker 部署时为命名卷 `mysql_data`，容器内 `/var/lib/mysql`）。
- 项目 `data/` 保存运行时文件，**不提交到 Git**：
  - `session_secret.txt`：会话签名密钥；
  - `weekly_roster.json`：每周名单种子（仅在没有已保存模板时读取）；
  - `imports/`：排班表与 CSV 模板等导入文件；
  - `app.sqlite`、`backups/`：旧版 SQLite 与迁移备份。
- 备份建议直接对 MySQL 做逻辑备份（如 `mysqldump`），或备份 Docker 卷。

## 从 SQLite 迁移

先停止旧版应用写入 SQLite，配置好**空的** MySQL 数据库，再执行：

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m server.migrate_mysql --source data/app.sqlite
.venv/bin/python -m server.provision_members
```

迁移会先备份 SQLite 到 `data/backups/`，再在单个 MySQL 事务中导入并逐表校验，保留密码哈希、班次 ID 与签到时间。目标库非空时停止，任何失败都会回滚。迁移完成后再启动新版服务。

## 测试

```bash
# Python 测试（含真实 MySQL 集成测试）
RUN_MYSQL_TESTS=1 .venv/bin/python -m unittest discover -s tests -v

# 前端逻辑测试（需 Node 18+）
node --test tests/*.cjs
```

MySQL 集成测试使用 `.env` 中的本地服务与 root 凭证，每个用例创建独立临时库并在结束时删除，不修改业务库。

## 安全

- 登录通过 `fetch` 发送 JSON，表单强制 POST；即使脚本未加载，密码也不会出现在网址栏或访问日志中。
- 会话与管理员 Cookie 有效期 4 小时；同一来源连续 8 次登录失败会限制 15 分钟。
- 登录接口只信任直连地址，不读取可伪造的 `X-Forwarded-For`。
- 已设置禁止页面被嵌套、禁止外链脚本、不发送 Referer、禁止 MIME 嗅探等响应头。
- 公网部署请使用 HTTPS，并设置 `SESSION_HTTPS_ONLY=1`。
- 本项目未内置 WAF 与限流之外的防护，公网部署建议放在反向代理之后。

## 开源协议

本项目采用 [MIT License](LICENSE)。
