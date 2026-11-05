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
│   ├── swap_store.py       双方调换值班与自动清理
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
│   ├── admin.html          管理端：概览、排班、调班、用户、外勤、设置
│   ├── schedule.js         页面切换、签到表单、班次编辑
│   ├── overview.js         月度统计、时间轴、周历、详情弹窗
│   ├── weekly.js / weekly-import.js   每周模板与 CSV 导入
│   ├── special.js          特殊排班
│   ├── swaps.js            调换值班
│   ├── members.js          账号列表、搜索与权限树
│   ├── field-admin.js      外勤看板
│   ├── status-editor.js    手工改判考勤/外勤的通用弹窗
│   ├── field-duty.js       成员端外勤登记
│   ├── field-confirm.js    成员端外勤确认
│   ├── shift-timeline.js   值班时间轴（含几何测试）
│   ├── checkin-window.js   签到窗口判定
│   ├── settings.js         其他设置
│   ├── logs.js             查看日志
│   └── styles.css / schedule.css  Material You 样式
├── sql/mysql_schema.sql    MySQL 建表语句
├── tests/                  Python 与 Node 测试
├── icon/                   站点与界面图标（components/ 为组件 SVG，symbol/ 为原有图标）
├── parment/svg/            MDI 图标原件库；新增图标先从这里拷到 icon/components/ 再引用
├── data/                   运行时数据（不提交）
│   ├── .env                数据库凭证与运行配置
│   ├── mysql/              本地 MySQL 文件
│   ├── mysql-config/       本地 MySQL 配置
│   ├── logs/               运行日志
│   ├── session_secret.txt  会话签名密钥
│   ├── weekly_roster.json  每周名单种子
│   └── imports/            排班表与 CSV 模板
├── start.sh / start.bat    启动脚本
└── compose.yaml            本地 MySQL 8.4
```

## 项目各部分使用方法

### 启动与首次配置

```bash
python3 -m server.init_data   # Windows 可用 python；无需先安装依赖
# 自动生成 data/.env 和随机数据库密码；远程数据库请编辑 data/.env
docker compose --env-file data/.env up -d --wait mysql
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
- **周排班翻页**：周历两侧的箭头查看上一周 / 下一周，范围覆盖有排班的最早到最晚一周；到边界时对应箭头变灰禁用，中间没有排班的周仍可翻到。翻到其他周时标题变为「周排班」，并出现「回到本周」。
- 点击本周卡片打开详情，再点击某个人名可改判考勤状态。
- **查看日志**：记录管理员与值班账号的操作，按时间倒序显示时间、操作账号、操作内容，可按账号筛选或搜索关键字。覆盖登录、账号增删改、权限与密码变更、排班/特殊排班/每周模板/生成排班/清除排班、调班、考勤与外勤改判、值班签到、外勤登记与确认、系统时间与值班时间设置。
- **异常统计**（在本周排班下方）：可切换「近 2 周 / 近 4 周」，左右两栏用横向柱状图列出迟到与旷班次数排行，柱右侧标注次数；次数相同按姓名拼音排序。历史不足所选周数时，统计窗口内已有的全部记录。

### 每日 / 每周 / 特殊排班 / 调换值班

- **每日排班**：按日期查看，点击卡片编辑或删除；删除会连同签到记录一起删除。
- **每周排班**：填写四个班次的时间与周一至周日人员，保存后核对勾选；用「下载 CSV 模板」与「一键导入」批量填人。
- **生成排班**：选择截止日期，按星期从今天生成到该日，已存在或冲突的班次会跳过。
- **特殊排班**：新增一次性班次，可在未来特殊排班列表中编辑或删除。
- **调换值班**：选择两位人员和各自的一个未来班次互换，需勾选「双方已协商完成并同意调班」。任一班次开始后不能删除；双方都签到且两个班次结束后，记录自动消失。
- **清除所有排班**：需输入确认语，删除全部班次与签到，保留模板和账号。

### 成员端外勤：登记与确认

- 「外勤管理」：按钮分三档 —— `点击登记`（状态 0）→ `等待确认`（状态 1，黄色）→ `登记完成`（状态 2，浅绿色且锁定）。点击只会从 0 变为 1，不会自动确认。
- 「外勤确认」：列出本月所有状态 1 的登记及登记时间。点「点击确认」变绿后卡片稍后消失、状态变为 2；点「删除」卡片立即消失、状态回到 0，可重新登记。
- 数据库 `field_duty.status` 取值 0/1/2；升级前已有的记录按 2（已确认）处理。

### 用户管理

- 顶部搜索框按姓名即时筛选。
- 卡片右侧可更改权限、更改密码、重置密码、停用/启用、删除账号。
- 「更改权限」弹窗为可折叠树，勾选父级会展开并选中全部子项。

### 外勤管理（管理员）

- 翻页查看各月参与情况，点击人员卡片切换已参加/未参加。
- **月份翻页**：与概览的周排班一致，标题行右侧用箭头查看上个月 / 下个月，范围覆盖有外勤记录的最早到最晚月份（本月始终在范围内）；到边界时对应箭头变灰禁用。离开本月后出现「回到本月」。
- **只统计已确认（状态 2）的外勤**；自己登记但未确认的记录不计入。
- 管理员修改的条目会显示「管理员修改」。

### 其他设置

- 设置提前打卡、迟到、旷班分钟数；旷班时间必须大于迟到时间。
- 系统时间：默认「自动设置」使用真实时间；取消后可指定日期与小时、分钟，并按该时刻开始计时。签到窗口、迟到/旷班判定、概览统计、外勤月份、调班与生成排班全部使用这个时钟，前端时间轴与按钮也会同步。下方始终显示当前系统时间。

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
| 更改排班 | 每日/每周/特殊排班、调换值班与其他设置 |
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

运行 `python3 -m server.init_data` 会创建 `data/.env`，按 `.env.example` 生成配置并随机生成两份独立的数据库密码。使用远程数据库时编辑 `data/.env`。环境变量优先于此文件。旧根目录 `.env` 会自动迁移；两处配置不一致时停止并提示合并，不覆盖配置。

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

本地 Docker 在空的 `data/mysql/` 中自动创建数据库和账号；远程 MySQL 请事先创建数据库并授予应用账号建表与读写权限；应用启动时会自动建表并补齐新增字段，不会覆盖旧数据。

## 启动

使用本地 Docker MySQL：

```bash
python3 -m server.init_data
docker compose --env-file data/.env up -d --wait mysql
./start.sh
```

Windows 使用 `start.bat`。启动脚本会创建项目内 `.venv`、安装依赖（默认 PyPI 失败时自动尝试国内镜像），初始化 `data/` 并读取 `data/.env`，然后监听 `0.0.0.0:50025`。手动运行 uvicorn 或维护命令也会初始化目录。初始化不会重置现有数据库、密码或配置。

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

- **业务数据**保存在 MySQL；本地 Docker 将 `data/mysql/` 挂载到容器 `/var/lib/mysql`，不再使用命名卷。已有命名卷部署应先导出 SQL 到 `data/backups/`，启动新的空库后导入；不要直接复制运行中的 MySQL 文件。
- 项目 `data/` 保存运行时文件，**不提交到 Git**：
  - `.env`：数据库凭证与本地配置；
  - `mysql/`：本地 MySQL 数据、证书与日志；
  - `mysql-config/runtime.cnf`：按本地文件系统大小写规则生成的 MySQL 配置；
  - `logs/`：QQ 机器人等运行日志；
  - `session_secret.txt`：会话签名密钥；
  - `weekly_roster.json`：每周名单种子（仅在没有已保存模板时读取）；
  - `imports/`：排班表与 CSV 模板等导入文件；
  - `app.sqlite`、`backups/`：旧版 SQLite 与迁移备份。
- 首次初始化创建 `data/`、配置及 `mysql/`、`mysql-config/`、`imports/`、`backups/`、`logs/`、`certs/` 子目录。SQLite 表和会话密钥按需创建；不生成包含真实人员的种子名单。
- SQL 导出统一放在 `data/backups/`，证书放在 `data/certs/`。`MYSQL_SSL_CA` 的相对路径相对于 `data/`。备份 MySQL 使用逻辑备份（如 `mysqldump`），或停库后备份 `data/mysql/`。
- `sql/mysql_schema.sql` 只有建表结构，保留在源码中；`.env.example` 只有占位配置。Git 忽略整个 `data/`，并额外忽略数据库文件、SQL 导出、私钥、证书及人员表格，防止误放到其他目录后被提交。

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

MySQL 集成测试使用 `data/.env` 中的本地服务与 root 凭证，每个用例创建独立临时库并在结束时删除，不修改业务库。

## 安全

- 登录通过 `fetch` 发送 JSON，表单强制 POST；即使脚本未加载，密码也不会出现在网址栏或访问日志中。
- 会话与管理员 Cookie 有效期 4 小时；同一来源连续 8 次登录失败会限制 15 分钟。
- 登录接口只信任直连地址，不读取可伪造的 `X-Forwarded-For`。
- 已设置禁止页面被嵌套、禁止外链脚本、不发送 Referer、禁止 MIME 嗅探等响应头。
- 公网部署请使用 HTTPS，并设置 `SESSION_HTTPS_ONLY=1`。
- 本项目未内置 WAF 与限流之外的防护，公网部署建议放在反向代理之后。

## 开源协议

本项目采用 [MIT License](LICENSE)。
