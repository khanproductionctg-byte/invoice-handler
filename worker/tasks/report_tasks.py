"""
Celery tasks for report generation and export.
"""
from celery import current_task
from worker.celery_worker import celery_app
from db.database import SessionLocal
from db.models import User, TenantUser, Tenant, Invoice, Customer, Payment, Expense, Report
from agents.reporter_agent import ReporterAgent
from agents.base_agent import AgentState
import logging
import json
import os
from datetime import date, timedelta
from calendar import monthrange

logger = logging.getLogger(__name__)

LLM_MODEL = os.getenv("LLM_MODEL", "nemotron-3-super")


def get_reporter_agent():
    """Get initialized reporter agent."""
    try:
        from langchain_community.llms import Ollama
        from langchain_core.tools import Tool
        from agents.reporter_agent import ReporterAgent
        llm = Ollama(model=LLM_MODEL)
        tools = [
            Tool(
                name="generate_ar_report",
                func=lambda x: _generate_ar_report(**json.loads(x) if x else {}),
                description="Generate accounts receivable aging report",
            ),
            Tool(
                name="generate_cash_flow_report",
                func=lambda x: _generate_cash_flow_report(**json.loads(x) if x else {}),
                description="Generate cash flow analysis report",
            ),
        ]
        return ReporterAgent(llm=llm, tools=tools)
    except Exception as e:
        logger.error(f"Failed to initialize reporter agent: {e}")
        return None


def _generate_ar_report(tenant_id: int, period_start: date, period_end: date) -> dict:
    db = SessionLocal()
    try:
        invoices = db.query(Invoice).filter(
            Invoice.tenant_id == tenant_id,
            Invoice.status.in_(["pending", "overdue"]),
            Invoice.invoice_date >= period_start,
            Invoice.invoice_date <= period_end,
        ).all()

        aging = {"current": 0.0, "30_days": 0.0, "60_days": 0.0, "90+_days": 0.0}
        for inv in invoices:
            due = float(inv.amount_due - inv.amount_paid)
            days_overdue = (date.today() - inv.due_date).days
            if days_overdue <= 0:
                aging["current"] += due
            elif days_overdue <= 30:
                aging["30_days"] += due
            elif days_overdue <= 60:
                aging["60_days"] += due
            else:
                aging["90+_days"] += due

        return {"aging_buckets": aging, "total_outstanding": sum(aging.values())}
    finally:
        db.close()


def _generate_cash_flow_report(tenant_id: int, period_start: date, period_end: date) -> dict:
    db = SessionLocal()
    try:
        payments = db.query(Payment).filter(
            Payment.tenant_id == tenant_id,
            Payment.payment_date >= period_start,
            Payment.payment_date <= period_end,
        ).all()
        expenses = db.query(Expense).filter(
            Expense.tenant_id == tenant_id,
            Expense.expense_date >= period_start,
            Expense.expense_date <= period_end,
        ).all()

        total_inflow = sum(float(p.amount) for p in payments)
        total_outflow = sum(float(e.amount) for e in expenses)
        return {
            "total_inflow": total_inflow,
            "total_outflow": total_outflow,
            "net_cash_flow": total_inflow - total_outflow,
            "payment_count": len(payments),
            "expense_count": len(expenses),
        }
    finally:
        db.close()


@celery_app.task(bind=True)
def generate_weekly_report(self, user_id: int = None, forecast: bool = False):
    """
    Celery task to generate a weekly report.
    Can be called with user_id (manual) or without (beat schedule).
    """
    logger.info(f"Generating weekly report with forecast={forecast}")

    try:
        db = SessionLocal()

        # Beat mode: process all active tenants if no user_id provided
        if user_id is None:
            tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
            logger.info(f"Beat mode: generating reports for {len(tenants)} tenants")
            
            results = []
            for tenant in tenants:
                try:
                    result = _generate_weekly_for_tenant(db, tenant.id, forecast)
                    results.append({"tenant_id": tenant.id, "status": "ok", "report_id": result.get("report_id")})
                except Exception as tenant_err:
                    logger.error(f"Report failed for tenant {tenant.id}: {tenant_err}")
                    results.append({"tenant_id": tenant.id, "status": "error", "error": str(tenant_err)})
            
            db.commit()
            return {"status": "completed", "tenants_processed": len(results), "results": results}
        else:
            # Manual mode: generate for specific user
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise ValueError(f"User with id {user_id} not found")

            tenant_user = db.query(TenantUser).filter(TenantUser.user_id == user_id).first()
            if not tenant_user:
                raise ValueError(f"No tenant association for user {user_id}")
            
            result = _generate_weekly_for_tenant(db, tenant_user.tenant_id, forecast)
            db.commit()
            return result

    except Exception as e:
        logger.error(f"Error generating weekly report: {str(e)}")
        self.update_state(state='FAILURE', meta={'error': str(e)})
        raise
    finally:
        if 'db' in locals():
            db.close()


def _generate_weekly_for_tenant(db, tenant_id: int, forecast: bool = False):
    """Helper to generate weekly report for a specific tenant."""
    from datetime import datetime
    
    today = date.today()
    period_start = today - timedelta(days=today.weekday() + 7)
    period_end = today - timedelta(days=today.weekday() + 1)

    ar_data = _generate_ar_report(tenant_id, period_start, period_end)
    cf_data = _generate_cash_flow_report(tenant_id, period_start, period_end)

    report = Report(
        tenant_id=tenant_id,
        report_type="weekly",
        title=f"Weekly Report {period_start} to {period_end}",
        content={"ar_aging": ar_data, "cash_flow": cf_data, "forecast": forecast},
        period_start=period_start,
        period_end=period_end,
    )
    db.add(report)
    db.flush()  # Get report ID without committing
    
    return {
        "tenant_id": tenant_id,
        "report_type": "weekly",
        "forecast_included": forecast,
        "status": "completed",
        "report_id": report.id,
        "period_start": str(period_start),
        "period_end": str(period_end),
    }


@celery_app.task(bind=True)
def generate_monthly_report(self, user_id: int = None, forecast: bool = False):
    """
    Celery task to generate a monthly financial report.
    Can be called with user_id (manual) or without (beat schedule).
    """
    logger.info(f"Generating monthly report with forecast={forecast}")

    try:
        db = SessionLocal()

        # Beat mode: process all active tenants if no user_id provided
        if user_id is None:
            tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
            logger.info(f"Beat mode: generating monthly reports for {len(tenants)} tenants")
            
            results = []
            for tenant in tenants:
                try:
                    result = _generate_monthly_for_tenant(db, tenant.id, forecast)
                    results.append({"tenant_id": tenant.id, "status": "ok", "report_id": result.get("report_id")})
                except Exception as tenant_err:
                    logger.error(f"Monthly report failed for tenant {tenant.id}: {tenant_err}")
                    results.append({"tenant_id": tenant.id, "status": "error", "error": str(tenant_err)})
            
            db.commit()
            return {"status": "completed", "tenants_processed": len(results), "results": results}
        else:
            # Manual mode: generate for specific user
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise ValueError(f"User with id {user_id} not found")

            tenant_user = db.query(TenantUser).filter(TenantUser.user_id == user_id).first()
            if not tenant_user:
                raise ValueError(f"No tenant association for user {user_id}")
            
            result = _generate_monthly_for_tenant(db, tenant_user.tenant_id, forecast)
            db.commit()
            return result

    except Exception as e:
        logger.error(f"Error generating monthly report: {str(e)}")
        self.update_state(state='FAILURE', meta={'error': str(e)})
        raise
    finally:
        if 'db' in locals():
            db.close()


def _generate_monthly_for_tenant(db, tenant_id: int, forecast: bool = False):
    """Helper to generate monthly report for a specific tenant."""
    from datetime import datetime
    
    today = date.today()
    _, last_day = monthrange(today.year, today.month)
    period_start = date(today.year, today.month, 1)
    period_end = date(today.year, today.month, last_day)

    ar_data = _generate_ar_report(tenant_id, period_start, period_end)
    cf_data = _generate_cash_flow_report(tenant_id, period_start, period_end)

    report = Report(
        tenant_id=tenant_id,
        report_type="monthly",
        title=f"Monthly Report {period_start} to {period_end}",
        content={"ar_aging": ar_data, "cash_flow": cf_data, "forecast": forecast},
        period_start=period_start,
        period_end=period_end,
    )
    db.add(report)
    db.flush()
    
    return {
        "tenant_id": tenant_id,
        "report_type": "monthly",
        "forecast_included": forecast,
        "status": "completed",
        "report_id": report.id,
        "period_start": str(period_start),
        "period_end": str(period_end),
    }


@celery_app.task(bind=True)
def export_report_to_format(self, report_id: int, format: str):
    """
    Celery task to export a report to a specified format (CSV, Excel, PDF).
    
    Args:
        report_id: ID of the report to export
        format: Export format (csv, excel, pdf)
    """
    import tempfile
    import os
    
    logger.info(f"Exporting report {report_id} to {format} format")
    
    try:
        db = SessionLocal()
        
        report = db.query(Report).filter(Report.id == report_id).first()
        if not report:
            raise ValueError(f"Report with id {report_id} not found")
        
        self.update_state(state='PROGRESS', meta={'step': 'Exporting report'})
        
        # Get report data
        report_data = report.content
        
        # Create temp directory for export
        temp_dir = tempfile.mkdtemp()
        
        if format.lower() == 'excel':
            from utils.report_generator import export_report_to_excel
            file_path = os.path.join(temp_dir, f"report_{report_id}.xlsx")
            success = export_report_to_excel(report_data, file_path)
        elif format.lower() == 'csv':
            from utils.report_generator import export_report_to_csv
            file_path = os.path.join(temp_dir, f"report_{report_id}.csv")
            success = export_report_to_csv(report_data, file_path)
        elif format.lower() == 'pdf':
            # PDF export - save content as text for now
            file_path = os.path.join(temp_dir, f"report_{report_id}.txt")
            with open(file_path, 'w') as f:
                import json
                f.write(json.dumps(report_data, indent=2))
            success = True
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        if not success:
            raise Exception(f"Export failed for format: {format}")
        
        # Read the exported file
        with open(file_path, 'rb') as f:
            file_data = f.read()
        
        # Clean up
        os.remove(file_path)
        os.rmdir(temp_dir)
        
        result = {
            "report_id": report_id,
            "format": format,
            "status": "completed",
            "message": f"Report {report_id} exported to {format} format",
            "file_size_bytes": len(file_data),
            "exported_at": datetime.now().isoformat()
        }
        
        logger.info(f"Report {report_id} exported to {format} format")
        return result
        
    except Exception as e:
        logger.error(f"Error exporting report {report_id} to {format}: {str(e)}")
        self.update_state(state='FAILURE', meta={'error': str(e)})
        raise
    finally:
        if 'db' in locals():
            db.close()