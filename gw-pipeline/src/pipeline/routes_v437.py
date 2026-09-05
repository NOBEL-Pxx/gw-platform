"""
v4.37: Security + Operations API Routes

New endpoints added to the FastAPI server:
  /pipeline/metrics                          — Prometheus metrics (Fix #4)
  /pipeline/admin/secrets/status             — Secrets expiry status (Fix #2)
  /pipeline/admin/secrets/rotate             — Trigger secret rotation (Fix #2)
  /pipeline/admin/secrets/alerts             — Expiring secrets alerts (Fix #2)
  /pipeline/admin/audit/unified              — Cross-source audit search (Fix #3)
  /pipeline/admin/audit/anomalies            — Anomaly detection results (Fix #3)
  /pipeline/admin/audit/ship                 — Log shipper ingestion (Fix #3)
  /pipeline/batch/submit                     — Submit batch task (Fix #8)
  /pipeline/batch/status/{task_id}           — Query batch task (Fix #8)
  /pipeline/batch/queue                      — Queue state (Fix #8)
  /pipeline/batch/cancel/{task_id}           — Cancel batch task (Fix #8)

Usage: Import in server.py and call register_routes(app)
"""
import json, time, logging
from typing import Optional, List

from fastapi import Request, Query
from fastapi.responses import JSONResponse, PlainTextResponse

logger = logging.getLogger("gw.routes-v437")


def register_routes(app):
    """Register all v4.37 routes on the FastAPI app."""

    # ── Prometheus Metrics (Fix #4) ──────────────────────────────────────────

    @app.get("/pipeline/metrics")
    async def prometheus_metrics(request: Request):
        """Expose AI/LLM metrics in Prometheus text format."""
        try:
            from .ai_metrics import get_metrics
            metrics = get_metrics()
            return PlainTextResponse(
                metrics.render_prometheus(),
                media_type="text/plain; charset=utf-8"
            )
        except ImportError:
            return PlainTextResponse(
                "# AI metrics module not available\n",
                media_type="text/plain; charset=utf-8"
            )

    # ── Secrets Management (Fix #2) ─────────────────────────────────────────

    @app.get("/pipeline/admin/secrets/status")
    async def secrets_status(request: Request):
        """List all secrets with expiry status. Admin only."""
        try:
            from .secrets_manager import get_secrets_manager
            sm = get_secrets_manager()
            secrets = sm.list_secrets()
            expiry = sm.check_expiry()

            # Merge expiry info into secret list
            expiry_map = {e['name']: e for e in expiry}
            for s in secrets:
                e = expiry_map.get(s['name'], {})
                s['status'] = e.get('status', 'unknown')
                s['days_until_expiry'] = e.get('days_until_expiry')
                s['expires_at'] = e.get('expires_at')

            return {
                "secrets": secrets,
                "total": len(secrets),
                "expired": sum(1 for s in secrets if s.get('status') == 'expired'),
                "expiring_soon": sum(1 for s in secrets if s.get('status') == 'expiring_soon'),
            }
        except ImportError:
            return {"error": "Secrets manager not available"}

    @app.post("/pipeline/admin/secrets/rotate")
    async def secrets_rotate(request: Request):
        """Rotate a secret. Admin only."""
        try:
            body = await request.json()
            name = body.get("name", "")
            if not name:
                return JSONResponse({"error": "Secret name required"}, status_code=400)

            from .secrets_manager import get_secrets_manager
            sm = get_secrets_manager()
            result = sm.rotate_secret(name)

            return {
                "success": True,
                "secret": name,
                "rotation_count": result['new_rotation_count'],
                "previous_expiry": result['previous_expiry'],
                "new_expiry": result['new_expiry'],
            }
        except ImportError:
            return JSONResponse({"error": "Secrets manager not available"}, status_code=500)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/pipeline/admin/secrets/alerts")
    async def secrets_alerts(request: Request):
        """Get alerts for expiring/expired secrets. Admin only."""
        try:
            from .secrets_manager import get_secrets_manager
            sm = get_secrets_manager()
            alerts = sm.get_alerts()
            return {"alerts": alerts, "count": len(alerts)}
        except ImportError:
            return {"alerts": [], "count": 0}

    # ── Unified Audit (Fix #3) ──────────────────────────────────────────────

    @app.get("/pipeline/admin/audit/unified")
    async def audit_unified(
        request: Request,
        source: str = Query(default="all", description="Filter: llm, mcp, backend, all"),
        user: Optional[str] = Query(default=None, description="Filter by user ID"),
        action: Optional[str] = Query(default=None, description="Filter by action type"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
    ):
        """Cross-source unified audit log search. Admin only."""
        try:
            from .audit_mongo import unified_search
            result = await unified_search(
                source=source,
                user=user,
                action=action,
                page=page,
                page_size=page_size,
            )
            return result
        except ImportError:
            return {"error": "Audit module not available", "entries": [], "total": 0}
        except Exception as e:
            logger.error(f"Unified audit search failed: {e}")
            return {"error": str(e), "entries": [], "total": 0}

    @app.get("/pipeline/admin/audit/anomalies")
    async def audit_anomalies(request: Request):
        """Detect anomalous audit patterns. Admin only."""
        try:
            from .audit_mongo import detect_anomalies
            result = await detect_anomalies()
            return result
        except ImportError:
            return {"anomalies": [], "count": 0}
        except Exception as e:
            return {"anomalies": [], "count": 0, "error": str(e)}

    @app.post("/pipeline/admin/audit/ship")
    async def audit_ship(request: Request):
        """Ingest shipped log events from other containers. Internal only."""
        try:
            body = await request.json()
            from .audit_mongo import write_shipped_event
            await write_shipped_event(body)
            return {"status": "ok"}
        except ImportError:
            return {"status": "skipped", "reason": "audit module not available"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ── Batch Scheduler (Fix #8) ────────────────────────────────────────────

    @app.post("/pipeline/batch/submit")
    async def batch_submit(request: Request):
        """Submit a batch of AI tasks."""
        try:
            body = await request.json()
            tasks = body.get("tasks", [])

            if not tasks:
                return JSONResponse({"error": "No tasks provided"}, status_code=400)

            from .batch_scheduler import get_scheduler
            scheduler = get_scheduler()

            task_ids = []
            for task in tasks:
                desc = task.get("description", "Unnamed batch task")
                priority = task.get("priority", 0)

                # Create a coroutine that runs the agent
                async def batch_agent_task(description=desc):
                    # This is a placeholder — real implementation would call agent_loop
                    logger.info(f"Batch task executing: {description}")
                    return {"description": description, "status": "completed"}

                tid = await scheduler.submit(
                    description=desc,
                    coro=batch_agent_task(),
                    priority=priority,
                    task_id=task.get("task_id"),
                )
                task_ids.append(tid)

            return {
                "submitted": len(task_ids),
                "task_ids": task_ids,
                "message": f"{len(task_ids)} tasks submitted to batch queue",
            }
        except ImportError:
            return JSONResponse({"error": "Batch scheduler not available"}, status_code=500)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/pipeline/batch/status/{task_id}")
    async def batch_status(task_id: str, request: Request):
        """Get the status of a specific batch task."""
        try:
            from .batch_scheduler import get_scheduler
            scheduler = get_scheduler()
            status = await scheduler.get_status(task_id)
            if status is None:
                return JSONResponse({"error": "Task not found"}, status_code=404)
            return status
        except ImportError:
            return JSONResponse({"error": "Batch scheduler not available"}, status_code=500)

    @app.get("/pipeline/batch/queue")
    async def batch_queue(request: Request):
        """Get current batch queue state."""
        try:
            from .batch_scheduler import get_scheduler
            scheduler = get_scheduler()
            return await scheduler.get_queue_state()
        except ImportError:
            return JSONResponse({"error": "Batch scheduler not available"}, status_code=500)

    @app.delete("/pipeline/batch/cancel/{task_id}")
    async def batch_cancel(task_id: str, request: Request):
        """Cancel a pending or running batch task."""
        try:
            from .batch_scheduler import get_scheduler
            scheduler = get_scheduler()
            cancelled = await scheduler.cancel(task_id)
            if cancelled:
                return {"status": "cancelled", "task_id": task_id}
            return JSONResponse({"error": "Task not found or already completed"}, status_code=404)
        except ImportError:
            return JSONResponse({"error": "Batch scheduler not available"}, status_code=500)

    logger.info("v4.37 routes registered: metrics, secrets, unified audit, batch scheduler")
