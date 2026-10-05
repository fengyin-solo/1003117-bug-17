"""矿山安全监测管理平台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
健康检查：GET /api/health
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import ROUTERS
from app.services.rescue import get_rescue_service
from app.store import store

rescue_service = get_rescue_service()


app = FastAPI(title="矿山安全监测管理平台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in ROUTERS:
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, object]:
    """健康检查：确认服务已经监听、示例数据已经就绪。"""
    return {"ok": True, "app": settings.app_name, "modules": len(store.module_names())}


@app.get("/api/overview")
def overview() -> dict[str, object]:
    """运营概览：把各业务模块的待处理量汇总成看板卡片。

    应急救援的待检/异常量改为按统一判定口径实时统计，避免老数据里
    pending/abnormal 脏字段和列表、详情对不上。
    """
    data = store.overview()
    rescue_stats = rescue_service.stats()
    for module in data["modules"]:
        if module["name"] == "rescue":
            module["pending"] = rescue_stats["待检"]
            module["abnormal"] = rescue_stats["已过期"] + rescue_stats["已报废"]
    pending_total = sum(int(item["pending"]) for item in data["modules"])
    abnormal_total = sum(int(item["abnormal"]) for item in data["modules"])
    data["cards"] = [
        {"label": "业务模块", "value": len(data["modules"])},
        {"label": "今日新增", "value": sum(int(item["created"]) for item in data["modules"])},
        {"label": "待处理", "value": pending_total},
        {"label": "异常量", "value": abnormal_total},
    ]
    return data
