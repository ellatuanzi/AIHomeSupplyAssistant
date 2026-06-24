# 家庭 AI 补货助手 MVP

这是一个私人家庭物品整理工具，重点先放在三件事：

- 记录物品放在哪里
- 管理家庭待办，例如“把车库的手纸拿到主卧洗手间”
- 记录低库存和待补货商品

补货之后可以可选上传小票、订单截图或购买页面截图，用来记录在哪里买、多少钱、是否划算和备注。系统不会自动购买任何商品。

## 当前简化版

为了减少授权和维护成本，默认版本不使用：

- Gmail 读取订单
- Google Sheets
- NFC
- 自动发送每日邮件

数据默认存在 app 自己的 SQLite 数据库里。打开 `/chat` 页面即可查看今日摘要、待办、低库存和补货记录。

## 本地安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` 最少只需要：

```bash
DATABASE_PATH="data/home_inventory.sqlite3"
USE_GOOGLE_SHEETS=false
GEMINI_API_KEY="你的 Gemini API Key"
```

`GEMINI_API_KEY` 用于截图/小票识别和更智能的建议；没有配置时，基础记录和待办仍可使用。

## 启动

```bash
uvicorn app.main:app --reload
```

常用页面：

- `http://localhost:8000/chat`
- `http://localhost:8000/receipts`
- `http://localhost:8000/docs`

## Chat 能做什么

可以输入：

- `主卧洗手间手纸低库存`
- `把车库的手纸拿到主卧洗手间`
- `wipe 搬运完成`
- `身体乳放在哪里？`
- `现在有哪些待办？`
- `现在有什么要买？`

系统会更新本地数据库，并在 `/chat` 页面显示最新摘要。

## 补货记录

补货后可以到 `/chat` 或 `/receipts` 上传：

- 小票照片
- 订单截图
- 购买页面截图
- 文本小票

一次最多 3 个文件。系统会尽量识别商品名、价格、店铺、规格，并去掉多张图片里的重复商品。

## 部署到 Render

项目包含 `render.yaml`，可以作为 Render Blueprint 使用。

Render 环境变量建议：

```text
DATABASE_PATH=data/home_inventory.sqlite3
USE_GOOGLE_SHEETS=false
ENABLE_GMAIL_ORDER_ANALYSIS=false
ENABLE_EMAIL_SUMMARY=false
GEMINI_API_KEY=你的 Gemini API Key
```

注意：Render 免费实例的本地文件可能不是长期持久存储。这个简化版优先解决“不再需要 Google 授权”的问题；如果之后想要更稳的数据持久化，可以再升级到 Render Disk、Postgres 或 Supabase。

## Boundaries

- No auto-purchase.
- No payment information is stored.
- Gmail order reading is disabled by default.
- Google Sheets is disabled by default.
- NFC is no longer part of the default workflow.

---

# Household Home Inventory Assistant MVP

A lightweight private household app for organizing supplies, tracking tasks, and keeping a restock list.

The current default version avoids Gmail, Google Sheets, NFC, and daily email. Data is stored in the app's own SQLite database. The main experience is `/chat`, where users can ask questions, update item locations, create or complete tasks, and mark items as low stock.

Optional receipt or order screenshot upload is available for tracking where something was bought, approximate price, and notes for future comparison. The app never auto-purchases anything.
