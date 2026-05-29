from app.models.recommendations import Recommendation
from app.config import get_settings


class EmailSummaryAgent:
    @staticmethod
    def pending_items(pending: list[dict[str, str]]) -> list[dict[str, str]]:
        return [row for row in pending if row.get("补货状态") == "待确认"]

    @classmethod
    def should_send(
        cls,
        recommendations: list[Recommendation],
        pending: list[dict[str, str]],
        order_insights: list[dict] | None = None,
    ) -> bool:
        return bool(recommendations or cls.pending_items(pending) or order_insights)

    def build(
        self,
        recommendations: list[Recommendation],
        pending: list[dict[str, str]],
        order_insights: list[dict] | None = None,
    ) -> tuple[str, str]:
        order_insights = order_insights or []
        pending_items = self.pending_items(pending)
        subject = (
            f"今日家庭补货提醒：{len(recommendations)} 件需要处理，"
            f"{len(order_insights)} 条订单分析"
        )

        lines = [
            "早上好，",
            "",
            "这是今天的家庭补货摘要。",
            "",
            "需要处理：",
        ]

        if recommendations:
            for index, rec in enumerate(recommendations, start=1):
                lines.extend(
                    [
                        "",
                        f"{index}. {rec.item_name}",
                        f"紧急度：{rec.urgency}",
                        f"推荐商品：{rec.product_title}",
                        f"推荐店铺：{rec.recommended_retailer}",
                        f"预估价格：{rec.estimated_price}",
                        f"推荐理由：{rec.reasoning}",
                        f"链接：{rec.product_url}",
                    ]
                )
        elif pending_items:
            lines.append("暂无今天新生成的补货推荐，但下面这些仍待确认：")
            for index, row in enumerate(pending_items, start=1):
                lines.extend(
                    [
                        "",
                        f"{index}. {row.get('商品名称', '')}",
                        f"紧急度：{row.get('紧急度', '')}",
                        f"推荐商品：{row.get('推荐商品', '')}",
                        f"推荐店铺：{row.get('推荐店铺', '')}",
                        f"预估价格：{row.get('预估价格', '')}",
                        f"推荐理由：{row.get('推荐理由', '')}",
                        f"链接：{row.get('商品链接', '')}",
                    ]
                )
        else:
            lines.append("暂无新的低库存商品。")

        lines.extend(["", "已下单：", "请在 Google Sheet 中查看状态为“已下单”的项目。"])

        lines.extend(["", "仍待确认："])
        if pending_items:
            lines.extend([f"- {row.get('商品名称')}: {row.get('推荐商品')}" for row in pending_items])
        else:
            lines.append("暂无。")

        lines.extend(["", "订单分析："])
        if order_insights:
            for insight in order_insights:
                lines.extend(
                    [
                        "",
                        f"- {insight.get('item_name', '未匹配商品')}",
                        f"  店铺：{insight.get('retailer', '')}",
                        f"  商品：{insight.get('product_title', '')}",
                        f"  价格：{insight.get('price', '')}",
                        f"  地址分类：{insight.get('address_category', '未识别')}",
                        f"  价格判断：{insight.get('price_judgment', '')}",
                        f"  补货预测：{insight.get('restock_prediction', '')}",
                        f"  健康/适用性提醒：{insight.get('health_or_fit_note', '')}",
                        f"  更好建议：{insight.get('better_suggestion', '')}",
                    ]
                )
        else:
            lines.append("暂无新的订单邮件分析。")

        lines.extend(
            [
                "",
                "Google Sheet：",
                f"https://docs.google.com/spreadsheets/d/{get_settings().google_sheet_id}/edit",
                "",
                "提醒：",
                "系统不会自动购买任何商品。请人工确认后再进入店铺完成下单。",
            ]
        )

        return subject, "\n".join(lines)
