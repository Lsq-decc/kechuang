# 共青团湖北大学委员会大学生科创实践中心管理系统

这是一个供管理员使用的 Flask + MySQL + PaddleOCR 管理系统。主流程为：

`维护成员资料 -> 上传课表截图 -> Qwen VL 直接识别 -> 手动修正 -> 保存课表 -> 查询/导出无课汇总`

成员不需要注册或登录，成员资料由管理员统一创建。管理员可以选择任意成员上传和修改课表，
查询某一时间段的无课成员，也可以按部门、教学周生成一张完整的成员无课矩阵表并导出 Excel。
删除成员时，会同步清理该成员的课表、上传记录和上传图片。

系统还提供两个日常工作模块：部门资料库用于分别存放综合事务部、项目培育部和宣传推广部
的文件夹与文件；待办事项用于按账号记录工作事项、标记完成状态并按重要程度排序。

## 1. 项目目录结构

```text
kechuang/
├─ app/
│  ├─ __init__.py              # Flask 应用工厂、数据库初始化、管理员初始化
│  ├─ ai_schedule_parser.py    # DeepSeek 文本模型结构化解析
│  ├─ api.py                   # 用户、上传、OCR、课表、无课查询 API
│  ├─ auth.py                  # 管理员登录、退出、当前用户
│  ├─ config.py                # MySQL、上传大小、OCR 等配置
│  ├─ decorators.py            # 登录和角色权限装饰器
│  ├─ extensions.py            # Flask-SQLAlchemy 实例
│  ├─ materials.py             # 部门资料库文件与文件夹 API
│  ├─ models.py                # 用户、上传、课程、查询记录模型
│  ├─ ocr_service.py           # PaddleOCR 懒加载与结果标准化
│  ├─ owner_detection.py       # 从图片右下角识别课表主人姓名
│  ├─ schedule_parser.py       # 星期、节次、周数、课程名称启发式解析
│  ├─ summary_export.py        # 无课汇总 Excel（XLSX）生成
│  ├─ table_layout.py          # 课表网格检测和 OCR 内容单元格归并
│  ├─ todos.py                 # 当前账号待办 API
│  ├─ views.py                 # HTML 页面路由和受保护图片访问
│  ├─ vision_schedule_parser.py # 视觉大模型直接识图
│  ├─ static/
│  │  ├─ css/style.css
│  │  └─ js/common.js
│  └─ templates/
│     ├─ base.html
│     ├─ login.html
│     ├─ dashboard.html
│     ├─ upload.html
│     ├─ batch_upload.html
│     ├─ review.html
│     ├─ query.html
│     ├─ my_schedule.html
│     ├─ users.html
│     ├─ materials.html
│     ├─ todos.html
│     ├─ admin_user_schedule.html
│     └─ summary.html
├─ instance/uploads/           # 上传的原图
├─ instance/materials/         # 部门资料库实际文件
├─ tests/
│  ├─ conftest.py
│  └─ test_flow.py
├─ .env.example
├─ docker-compose.yml
├─ requirements.txt
├─ requirements-ocr.txt
├─ schema.sql
├─ run.py
└─ README.md
```

## 2. MySQL 建表 SQL

完整 SQL 位于 [schema.sql](schema.sql)，包含：

- `users`：用户名、密码哈希、姓名、学号/工号、部门、角色。
- `schedule_uploads`：上传文件、OCR 原文、OCR 结构化草稿和确认状态。
- `courses`：星期、开始节次、结束节次、课程名称、周数、地点、备注。
- `query_logs`：无课查询条件和结果数量。
- `material_folders`：三个部门空间中的多级文件夹。
- `material_files`：资料文件元数据及服务器存储键。
- `todo_items`：当前管理员自己的待办、重要程度和完成状态。

核心表结构如下：

```sql
CREATE DATABASE IF NOT EXISTS kechuang
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE kechuang;

CREATE TABLE users (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    username VARCHAR(50) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(50) NOT NULL,
    student_id VARCHAR(50) NULL,
    department VARCHAR(100) NOT NULL DEFAULT '未设置',
    role VARCHAR(20) NOT NULL DEFAULT 'member',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_username (username),
    UNIQUE KEY uq_users_student_id (student_id),
    KEY ix_users_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE schedule_uploads (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(255) NOT NULL,
    image_path VARCHAR(500) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    ocr_text TEXT NULL,
    ocr_result JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_uploads_stored_filename (stored_filename),
    CONSTRAINT fk_uploads_user FOREIGN KEY (user_id)
      REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE courses (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    upload_id INT UNSIGNED NULL,
    weekday TINYINT UNSIGNED NOT NULL,
    start_period TINYINT UNSIGNED NOT NULL,
    end_period TINYINT UNSIGNED NOT NULL,
    course_name VARCHAR(150) NOT NULL,
    weeks VARCHAR(255) NOT NULL DEFAULT '',
    location VARCHAR(150) NOT NULL DEFAULT '',
    note VARCHAR(255) NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_courses_time_lookup (weekday, start_period, end_period),
    CONSTRAINT fk_courses_user FOREIGN KEY (user_id)
      REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_courses_upload FOREIGN KEY (upload_id)
      REFERENCES schedule_uploads (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

应用启动时会在 `AUTO_CREATE_DB=true` 时执行 `db.create_all()`，并按 `.env`
配置自动创建首个管理员。正式环境建议先执行 `schema.sql`，再关闭自动建表。

## 3. Flask 后端代码

后端入口是 [run.py](run.py)，应用工厂位于 [app/__init__.py](app/__init__.py)。

已实现的接口：

| 方法 | 路径 | 权限 | 用途 |
| --- | --- | --- | --- |
| POST | `/api/auth/register` | 已停用 | 成员注册已关闭 |
| POST | `/api/auth/login` | 公开 | 管理员登录 |
| POST | `/api/auth/logout` | 登录 | 退出 |
| GET | `/api/auth/me` | 管理员 | 当前管理员 |
| GET | `/api/users` | 管理员 | 成员列表 |
| POST | `/api/users` | 管理员 | 新建成员 |
| PATCH | `/api/users/<id>` | 管理员 | 更新成员账号和密码 |
| DELETE | `/api/users/<id>` | 管理员 | 删除账号、课表和上传文件 |
| POST | `/api/schedules/upload` | 管理员 | 为指定成员上传截图并执行 OCR |
| GET | `/api/schedules/uploads/<id>` | 管理员 | 读取 OCR 待确认草稿 |
| POST | `/api/schedules/save` | 管理员 | 保存指定成员课表 |
| GET | `/api/schedules/users/<id>` | 管理员 | 查看指定成员课表 |
| DELETE | `/api/schedules/courses/<id>` | 管理员 | 删除课程 |
| GET | `/api/availability` | 管理员 | 查询指定时间段的无课成员 |
| GET | `/api/availability-summary` | 管理员 | 生成部门成员无课汇总预览 |
| GET | `/api/availability-summary/export` | 管理员 | 导出部门无课汇总 `.xlsx` |
| POST | `/api/availability-overrides` | 管理员 | 修改成员某周某时段的无课状态 |
| DELETE | `/api/availability-overrides` | 管理员 | 恢复成员该周由课表自动判断的状态 |
| GET | `/api/admin/stats` | 管理员 | 管理首页统计 |
| GET | `/api/departments` | 管理员 | 查询已有部门 |
| GET | `/api/materials` | 管理员 | 读取指定部门、文件夹下的目录与文件 |
| POST | `/api/materials/folders` | 管理员 | 在部门空间中新建多级文件夹 |
| DELETE | `/api/materials/folders/<id>` | 管理员 | 递归删除文件夹及其内容 |
| POST | `/api/materials/files` | 管理员 | 批量上传文件到指定文件夹 |
| GET | `/api/materials/files/<id>/content` | 管理员 | 查看或下载资料文件 |
| DELETE | `/api/materials/files/<id>` | 管理员 | 删除资料文件 |
| GET | `/api/todos` | 管理员 | 获取自己的待办并按状态筛选、按重要程度排序 |
| POST | `/api/todos` | 管理员 | 添加待办 |
| PATCH | `/api/todos/<id>` | 管理员 | 修改待办完成状态、重要程度或内容 |
| DELETE | `/api/todos/<id>` | 管理员 | 删除待办 |

查询示例：

```text
GET /api/availability?weekday=1&start_period=1&end_period=2&week_number=3&department=项目办公室
```

无课判断会检查星期和节次，并在填写 `week_number` 时进一步检查“1-16周”“单周”
“双周”等周数描述。没有可解析周数信息的课程会保守地视为每周都有课。

汇总导出的部门下拉框支持“所有部门”或指定部门，并生成一张“成员 × 星期 × 课程块”的总表。
页面下方另有课表式“总无课表”：星期横排、节次纵排，每个单元格显示无课成员。选择成员后
可通过单元格右上角的 `+`、`−` 调整该时段无课状态，手动修改会按教学周保存，并优先于课表
自动判断；点击“恢复课表判断”可清除该成员该周的手动覆盖。Excel 导出只包含课表式
`总无课表` 工作表，不再导出上方那种成员课表矩阵。
每个星期下的课程块固定为第 `1-2`、`3-4`、`5-6`、`7-8`、`9-10` 节：

- 绿色单元格表示成员在对应节次无课。
- 黄色单元格显示该成员在该节次的课程名称。
- 表尾标出全部成员都为无课的时段，并给出每名成员的无课节数。

## 4. PaddleOCR 识别和课表解析

PaddleOCR 在 [app/ocr_service.py](app/ocr_service.py) 中懒加载，只有首次上传时才会初始化模型。
服务同时兼容 PaddleOCR 2.x 的 `ocr(...)` 返回结构，以及部分 3.x 输出字段。

[app/schedule_parser.py](app/schedule_parser.py) 根据文字内容和坐标执行启发式解析：

1. 识别“周一”到“周日”和“星期一”到“星期日”。
2. 识别“第1-2节”“3-4节”和常见上下课时间。
3. 识别“1-16周”“1-8,10-16周”“单周”“双周”。
4. 优先读取文字中的明确信息，否则按表头横坐标和节次行纵坐标估算。
5. OCR 结果全部进入可编辑表格，用户必须确认后才变成正式课表。

星期列会根据全部星期表头生成列中心网格。如果某个表头被 OCR 误识为相邻星期，
解析器会根据表头的横向顺序修正列编号，并按文字框与列的横向重叠面积判断星期，
减少“周四被识别成周三”这类整列偏移。

上传时还会检查图片右下角区域，提取“姓名：张三”“学生姓名：张三”或独立的
2-6 字中文姓名。自动上传模式会优先匹配已有成员，没有同名成员时自动创建成员；
如果识别置信度过低或存在同名记录，则要求管理员手工选择，避免误建成员。

课表截图格式差异较大，解析结果不能保证一次完全准确，因此不直接自动入库；
上传后统一进入手动修正页面。

## 5. 前端页面

页面采用原生 HTML、CSS、JavaScript：

- `/login`：登录页。
- `/dashboard`：首页和快速入口。
- `/upload`：先选择成员，再上传该成员的课表截图。
- `/batch-upload`：一次选择多张截图，按文件名或图片右下角姓名匹配成员并逐张完成识别。
- `/review/<upload_id>`：OCR 结果修正、新增、删除和保存。
- `/query`：按星期、节次、周次和部门查询无课成员。
- `/summary`：自动生成部门成员无课汇总，并导出 Excel。
- `/materials`：在三个部门空间中新建文件夹、上传和下载资料。
- `/todos`：添加和删除待办，切换完成状态，修改重要程度并排序。
- `/users`：创建、编辑和删除成员资料。
- `/admin/users/<id>/schedule`：管理员查看并修改指定账号的课表。

静态资源位于 `app/static/`，页面模板位于 `app/templates/`。

## 6. 运行说明

### 6.1 创建并启动 MySQL

已安装 Docker Desktop 时，在项目根目录执行：

```powershell
docker compose up -d mysql
```

首次创建容器时会自动执行 `schema.sql`。

也可以使用本机 MySQL：

```sql
SOURCE D:/lsq_codex/kechuang/schema.sql;
```

### 6.2 安装 Python 依赖

```powershell
cd D:\lsq_codex\kechuang
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-ocr.txt
```

`requirements-ocr.txt` 默认安装 CPU 版 `paddlepaddle==2.6.2`。如果机器已有匹配
CUDA 的 PaddlePaddle，请按 PaddlePaddle 官方方式安装对应 GPU 包，不要覆盖现有版本。

首次识别时，PaddleOCR 会自动下载中文检测、识别和方向分类模型到
`instance/paddle_runtime`。该目录已加入 `.gitignore`，后续启动不会重复下载。

### 6.3 配置环境变量

```powershell
Copy-Item .env.example .env
```

编辑 `.env`：

```dotenv
SECRET_KEY=请替换为随机字符串
DATABASE_URL=mysql+pymysql://root:root@127.0.0.1:3306/kechuang?charset=utf8mb4
ADMIN_USERNAME=admin
ADMIN_PASSWORD=Admin123!
ADMIN_NAME=系统管理员
ADMIN_STUDENT_ID=admin
ADMIN_DEPARTMENT=大学生科创实践中心
AUTO_CREATE_DB=true
OCR_ENGINE=paddle
PADDLE_RUNTIME_HOME=instance/paddle_runtime
AI_PARSER_ENABLED=false
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_TIMEOUT=60
DEEPSEEK_MAX_TOKENS=4096
AI_PARSER_MAX_ITEMS=400
VISION_PARSER_ENABLED=false
VISION_API_KEY=
VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VISION_MODEL=qwen-vl-max
VISION_TIMEOUT=120
VISION_MAX_TOKENS=4096
VISION_MAX_IMAGE_WIDTH=2000
MAX_CONTENT_LENGTH_MB=50
```

首次启动会自动创建 `admin` 账号。已有同名账号时不会覆盖密码。

### 6.4 DeepSeek 文本模型辅助解析

如果只有 DeepSeek 文本模型，不需要额外购买视觉模型。系统会继续使用 PaddleOCR
提取文字、坐标和置信度，并先检测课表横竖线、星期表头和节次标签，将文字归入对应
课表单元格。只有小格内部的课程文字会交给 DeepSeek 文本模型整理成课程 JSON，
表头、节次标签和边框信息不会参与课程解析。原图不会发送给 DeepSeek。

启用方式：

```dotenv
AI_PARSER_ENABLED=true
DEEPSEEK_API_KEY=你的DeepSeek密钥
DEEPSEEK_MODEL=deepseek-chat
```

该模式适合降低费用：每次只发送课表 OCR 片段，不发送图片；DeepSeek 请求失败、
超时或返回非法 JSON 时，系统会自动回退到原有规则解析器。

如 DeepSeek 文本模式仍不够准确，可以直接把原图交给 Qwen 视觉模型：

```dotenv
VISION_PARSER_ENABLED=true
VISION_API_KEY=你的视觉模型密钥
VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VISION_MODEL=qwen-vl-max
```

该模式不依赖 PaddleOCR，上传后的流程是：

```text
原图 -> Qwen VL -> 课程 JSON -> 页面展示 -> 管理员核对保存
```

Qwen 会同时返回课表主人姓名，用于批量上传时自动匹配或创建成员。视觉模型失败时，
系统才会回退到“PaddleOCR + 单元格解析 + DeepSeek”，最后回退到规则解析。
只要视觉模型返回课程，周数字段必须填写；无法从图片判断时会填写“每周”，避免
无课汇总缺失课程。

### 6.5 启动项目

```powershell
python run.py
```

浏览器访问：

```text
http://127.0.0.1:5000
```

健康检查：

```text
http://127.0.0.1:5000/health
```

### 6.6 测试主流程

1. 使用 `admin / Admin123!` 登录。
2. 在“成员管理”中创建成员资料。
3. 进入“上传课表”，先选择成员，再选择课表截图并上传。
   上传页也可以选择“自动识别右下角姓名”，系统会匹配已有成员或自动创建新成员。
   批量录入时可进入“批量上传”，未指定成员的行会自动识别图片右下角姓名。
4. 在修正页核对星期、节次、课程名称和周数，新增或删除错误课程。
5. 选择“覆盖当前课表”或“追加到当前课表”，点击“确认保存”。
6. 进入“无课查询”，选择星期、节次和可选周次查询指定时间。
7. 进入“汇总导出”，选择部门和教学周，自动生成总表和课表式总无课表，并导出 Excel。
8. 进入“部门资料”，切换部门后新建文件夹或上传照片、文档等资料。
9. 进入“待办事项”，添加待办、切换完成状态，并按重要程度筛选和排序。
10. 在“成员管理”中可编辑资料、管理成员课表或删除成员。

命令行测试：

```powershell
python -m pytest -q
```

测试使用内存 SQLite 和模拟 OCR 返回，不会修改 MySQL 数据。

Flask 已启动且 MySQL 可用时，还可以执行真实 HTTP 冒烟测试：

```powershell
python scripts/smoke_test.py
```

脚本会自动登录、上传测试图片、保存一条测试课程、执行无课查询并删除测试课程。

## 7. 初版边界

- 暂未实现 Excel 导入，但上传接口和课程模型可以继续扩展 Excel 解析。
- OCR 解析是启发式规则，合并单元格、复杂背景和特殊排版的课表必须人工核对。
- 已启用 CSRF 校验和 HTTPS 安全 Cookie；验证码、审计后台和密码找回尚未实现。
- 无课汇总按教学周生成；如果课程未写明可解析周数，会保守地视为每周都有课。
- 当前单张截图保存时会默认“覆盖当前课表”，也提供“追加”模式；后续可增加按学期区分课表。
- 无课查询按节次执行；若学校不同校区的作息时间不同，需要继续补充作息时间配置。
- 部门资料权限目前对所有管理员开放；如需“只能访问本部门”的隔离，可在现有部门字段基础上继续细化。

## 8. 云服务器、域名和 HTTPS 部署

项目已经提供生产部署文件：

- `Dockerfile`：Python 3.11、PaddleOCR、Gunicorn 应用镜像。
- `docker-compose.prod.yml`：MySQL、Flask 应用和 Caddy HTTPS 反向代理。
- `deploy/Caddyfile`：自动申请免费 Let's Encrypt 证书。
- `.env.production.example`：生产环境变量模板。
- `scripts/deploy_prod.sh`：一键构建并启动。
- `scripts/backup_mysql.sh`：MySQL 备份。

### 8.1 云服务器建议

建议配置：

- Ubuntu 22.04 或 24.04
- 2 核 CPU、4 GB 内存起步
- 40 GB 以上系统盘
- 安全组放行 `22`、`80`、`443`
- 不向公网开放 `3306` 和 `8000`

PaddleOCR 首次识别时还需要下载模型，内存较低可能导致进程被系统终止。

### 8.2 域名解析

在域名服务商添加 A 记录：

```text
kechuang.example.com -> 云服务器公网 IP
```

等待解析生效后，Caddy 会在首次启动时自动申请 HTTPS 证书。

### 8.3 安装 Docker

在 Ubuntu 服务器执行：

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
newgrp docker
docker --version
docker compose version
```

### 8.4 上传项目和配置

将项目上传到服务器后：

```bash
cd /opt/kechuang
cp .env.production.example .env.production
```

编辑 `.env.production`，至少替换：

```dotenv
DOMAIN=kechuang.example.com
SECRET_KEY=使用随机长字符串
MYSQL_PASSWORD=数据库强密码
MYSQL_ROOT_PASSWORD=数据库root强密码
DATABASE_URL=mysql+pymysql://kechuang:数据库强密码@mysql:3306/kechuang?charset=utf8mb4
ADMIN_PASSWORD=管理员强密码
```

数据库密码包含 `@`、`:`、`/` 等字符时，`DATABASE_URL` 中必须进行 URL 编码。

### 8.5 启动生产服务

```bash
bash scripts/deploy_prod.sh
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

查看日志：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f app
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f caddy
```

访问：

```text
https://kechuang.example.com
```

### 8.6 数据持久化和备份

MySQL 数据、上传图片、PaddleOCR 模型和 HTTPS 证书都存放在 Docker named volume 中，
容器重建不会丢失。执行备份：

```bash
bash scripts/backup_mysql.sh
```

备份文件写入 `backups/`。正式使用后建议用 `cron` 每日执行，并把备份同步到对象存储
或另一台机器。
