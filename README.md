# 家庭 AI 补货助手 MVP

这个项目是一个实用优先的家庭补货助手 MVP：家里有人发现日用品快用完时，用 NFC、语音快捷指令或网页入口记录一下；系统每天扫描 Google Sheet，生成中文补货推荐，并通过 Gmail 发每日摘要。系统只推荐，不会自动购买。

## MVP 工作流

1. 用户轻触 NFC 标签，或通过语音/网页记录低库存。
2. FastAPI 后端把事件写入 Google Sheet 的 `低库存记录`。
3. 每日 Agent 读取 `库存清单`、`低库存记录`、`购买历史`。
4. 系统生成 Amazon、Costco、Walmart、Target 搜索链接。
5. OpenAI 根据偏好品牌、购买历史和紧急度生成中文推荐理由。
6. 推荐写入 `补货推荐`。
7. 系统读取 Gmail 里的订单、发货、送达邮件，提取购买记录、收货地址，并做价格/补货/适用性分析。
8. Gmail 发中文每日摘要和订单分析。
9. 用户人工打开链接并确认是否下单。

如果当天没有新的低库存推荐，且 `补货推荐` 里没有 `待确认` 项目，系统不会发送空日报。

## Google Sheet 表结构

项目会使用 4 个中文分表：

- `库存清单`
- `低库存记录`
- `购买历史`
- `订单分析`
- `补货推荐`

商品名称、品牌、店铺、规格可以保留英文，例如 `Toilet Paper`、`Charmin`、`Costco`。界面字段、状态、紧急度和推荐理由以中文为主。

常用状态：

- `待确认`
- `已下单`
- `已跳过`
- `需要更好选项`

紧急度：

- `低`
- `中`
- `高`
- `紧急`

## 本地安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

然后编辑 `.env`：

```bash
GOOGLE_SHEET_ID="你的 Google Sheet ID"
GOOGLE_CREDENTIALS_FILE="credentials/google_oauth_client.json"
GOOGLE_TOKEN_FILE="credentials/google_token.json"
GMAIL_SENDER_EMAIL="你的 Gmail 地址"
DAILY_SUMMARY_TO_EMAIL="接收摘要的邮箱"
OPENAI_API_KEY="你的 OpenAI API Key"
```

## Google API 设置

1. 在 Google Cloud Console 创建项目。
2. 启用 Google Sheets API 和 Gmail API。
3. 创建 OAuth Desktop Client。
4. 下载 JSON，放到：

```text
credentials/google_oauth_client.json
```

第一次运行脚本时会打开浏览器授权，并生成：

```text
credentials/google_token.json
```

## 初始化 Google Sheet

先创建一个空 Google Sheet，把 ID 填入 `.env`，然后运行：

```bash
python scripts/setup_google_sheet.py
```

这个脚本会创建中文分表、写入表头，并添加几个示例库存项目。

## 启动 API

```bash
uvicorn app.main:app --reload
```

打开：

```text
http://localhost:8000/docs
```

## NFC 示例

把 NFC 标签配置成打开这样的 URL：

```text
http://localhost:8000/nfc/toilet_paper
```

如果部署到云端，把域名替换成你的服务地址即可。

扫描 NFC 后会先打开一个手机确认页，用户可以选择：

- `低库存`
- `已经没有库存`
- `取消`

确认后才会写入 Google Sheet。

## 常用接口

记录低库存：

```http
POST /events/low-stock
```

```json
{
  "item_id": "toilet_paper",
  "source": "NFC",
  "urgency": "中",
  "note": "只剩几卷"
}
```

手动触发每日 Agent：

```http
POST /agent/daily-run
```

按 07:00 发送规则触发每日 Agent：

```http
POST /agent/daily-run-if-due
```

手动触发 Gmail 订单分析：

```http
POST /agent/order-analysis
```

Gmail 订单分析默认只读取 `order received`、`order confirmation`、`your order`、`ordered` 这类下单确认邮件，会过滤 shipped、delivered、promotion、deal、sale 等非订单确认邮件。

上传购物小票：

```http
POST /receipts/upload
```

表单字段名：

```text
file
```

文本小票可直接解析；图片小票在配置 OpenAI API Key 后可由视觉模型读取。PDF 小票在 MVP 中会先按文本尝试解析，复杂 PDF 后续可接 OCR。

HSA/FSA 候选记录：

- 系统会用关键词识别可能属于 HSA/FSA 的商品，例如 `anti-itch`、`hydrocortisone`、`bandage`、`sunscreen`、`ibuprofen` 等。
- 命中的商品会写入单独的 Google Sheet：默认名称是 `HSA 候选记录`，分表是 `HSA候选`。
- 如果是上传小票识别出的 HSA/FSA 候选，原始小票文件会上传到这张 HSA Sheet 所在的 Google Drive 文件夹。
- 这些记录只是“可能符合”，最终是否能报销仍需要人工确认。
- 如已有专门的 HSA Sheet，可配置 `HSA_SHEET_ID`；否则系统会自动在主补货表同一个 Drive 文件夹中创建。

更新推荐状态：

```http
POST /recommendations/{recommendation_id}/status
```

```json
{
  "reorder_status": "已下单"
}
```

## 每日定时运行

推荐使用带补发保护的脚本：

```bash
python scripts/run_due_daily_agent.py
```

发送逻辑：

- 每天 07:00 后才会尝试发送。
- 如果 07:00 时电脑没开机或没联网，开机/联网后再次运行脚本会自动补发。
- `发送记录` 分表会记录当天是否已经完成。
- 每天最多完成一次，避免反复联网导致重复发送。
- 如果运行失败，会记录为 `失败`，之后可以再次尝试。

本地 cron 可以每天 07:00 调一次：

```cron
0 7 * * * cd "/Users/qingcai/Documents/household AI replenishment assistant" && .venv/bin/python scripts/run_due_daily_agent.py
```

为了支持“开机后补发”，可以把同一个脚本也配置成登录/开机时运行。脚本本身会检查 `发送记录`，所以重复启动不会重复发送。

也可以后续改成 GitHub Actions、Cloud Run Jobs、Render Cron 或 Railway；仍建议调用 `scripts/run_due_daily_agent.py`。

## 部署到 Render

项目包含 `render.yaml`，可以作为 Render Blueprint 使用。
项目同时包含 `.python-version`，并在 `render.yaml` 里设置了 `PYTHON_VERSION=3.12.2`，避免 Render 默认使用过新的 Python 版本导致依赖构建失败。

推荐步骤：

1. 把项目推到 GitHub。
2. 在 Render 创建 `Blueprint`，选择这个 GitHub 仓库。
3. Render 会读取 `render.yaml` 并创建 Web Service。
4. 在 Render 的 Environment 里填入：

```text
GOOGLE_SHEET_ID
GOOGLE_OAUTH_CLIENT_JSON
GOOGLE_TOKEN_JSON
GMAIL_SENDER_EMAIL
DAILY_SUMMARY_TO_EMAIL
OPENAI_API_KEY
```

本地运行下面命令，可以把 Google OAuth 文件和 token 转成适合粘贴到 Render 的环境变量值：

```bash
python scripts/print_render_env.py
```

部署完成后，把 NFC 标签里的 URL 改成 Render 域名：

```text
https://你的-render-service.onrender.com/nfc/toilet_paper
```

每日任务可以在 Render 里单独创建 Cron Job，命令：

```bash
python scripts/run_daily_agent.py
```

只跑 Gmail 订单分析：

```bash
python scripts/run_order_analysis.py
```

如果新增了 Gmail 读取权限，需要重新 Google OAuth 授权，并更新 Render 的 `GOOGLE_TOKEN_JSON`。

每日邮件底部会包含 Google Sheet 链接，方便直接查看和修改状态。

订单分析会识别 `收货地址` 并写入 `地址分类`。默认地址由环境变量配置：

```text
DEFAULT_SHIPPING_ADDRESS="102 Montelena Ct"
```

## 重要边界

- 不自动购买。
- 不保存支付信息。
- NFC 只作为低摩擦记录入口。
- Google Sheet 是唯一可信数据源。
- 推荐链接优先使用搜索链接，避免脆弱和不合规的网页抓取。
