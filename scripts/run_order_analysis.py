"""Deprecated entrypoint kept for old Render cron jobs.

The MVP no longer reads Gmail order emails. Purchases can be recorded by
uploading a receipt or order screenshot from /chat or /receipts.
"""

import json


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "status": "跳过",
                "reason": "订单邮件读取已关闭。请在 /chat 上传小票或订单截图进行可选补录。",
                "order_insights_created": 0,
            },
            ensure_ascii=False,
        )
    )
