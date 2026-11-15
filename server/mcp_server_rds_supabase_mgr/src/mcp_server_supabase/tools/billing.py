"""Prepaid order tools: query, guarded payment, unpaid-order cancellation."""
from typing import Any

from huaweicloud_mcp_core import ToolRisk, guard

from mcp_server_supabase.service.billing import BillingOperations


def register(server):
    service = BillingOperations()

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def get_supabase_order(order_id: str, limit: int = 20, marker: str | None = None) -> dict[str, Any]:
        """查询 RDS Supabase 包周期订单（状态、金额、币种与分页明细）。未支付不代表应用或实例已开通；公测期应用免费，包周期费用仅涉托管实例。"""
        return await service.get_order(order_id=order_id, limit=limit, marker=marker)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def pay_supabase_order(
        order_id: str, expected_amount: str, currency: str,
        confirm: bool = False, plan_id: str | None = None,
    ) -> dict[str, Any]:
        """支付一笔待支付包周期订单，两段式提交。expected_amount 须同时等于 official_amount 与 amount_after_discount，有折扣即拒绝；单次提交，歧义结果不自动重试。"""
        return await service.pay_order(
            order_id=order_id, expected_amount=expected_amount, currency=currency,
            confirm=confirm, plan_id=plan_id,
        )

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def cancel_supabase_order(order_id: str, confirm: bool = False, plan_id: str | None = None) -> dict[str, Any]:
        """取消一笔包周期订单以放弃待付款单，两段式提交。仅未支付订单可取消，操作不可逆；已支付资源须走独立退订流程，重复取消幂等处理。"""
        return await service.cancel_order(order_id=order_id, confirm=confirm, plan_id=plan_id)
