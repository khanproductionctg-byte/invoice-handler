"""
ReporterAgent for generating financial reports and alerts.
"""
import logging
import os
from typing import Any, Dict, List, Optional
from datetime import datetime, date, timedelta
from calendar import monthrange
import json
import pandas as pd
from decimal import Decimal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from .base_agent import BaseAgent, AgentState
from db.database import SessionLocal, get_tenant_session
from db.models import Invoice, Expense, Payment, Report
from utils.report_generator import generate_financial_report, export_report_to_excel
from utils.alert_system import check_alert_conditions, send_alert

logger = logging.getLogger(__name__)


# Define tool input schemas
class GenerateReportInput(BaseModel):
    report_type: str = Field(description="Type of report: weekly, monthly, custom")
    period_start: date = Field(description="Start date for report period")
    period_end: date = Field(description="End date for report period")
    user_id: int = Field(description="ID of the user")
    forecast: bool = Field(description="Whether to include forecasting in the report", default=False)

class ExportReportInput(BaseModel):
    report_id: int = Field(description="ID of the report to export")
    format: str = Field(description="Export format: excel, csv, pdf")

class CheckAlertsInput(BaseModel):
    user_id: int = Field(description="ID of the user to check alerts for")

class ReporterAgent(BaseAgent):
    """
    Agent responsible for:
    - Generating weekly/monthly financial reports
    - Creating alerts for overdue amounts, unusual expenses, etc.
    - Exporting reports in various formats (Excel, CSV, PDF)
    """

    def __init__(self, llm: Any, tools: List[BaseTool]):
        """
        Initialize the ReporterAgent.

        Args:
            llm: Language model instance
            tools: List of tools available to this agent
        """
        super().__init__(llm, tools, "ReporterAgent")

    def process(self, state: AgentState) -> AgentState:
        """
        Process reporting and alerting tasks.

        Args:
            state: Current agent state containing input data

        Returns:
            Updated agent state with reporting results
        """
        logger.info(f"ReporterAgent processing state: {state.agent_id}")
        db = None

        try:
            # Extract input data
            user_id = state.input_data.get("user_id")
            if not user_id:
                raise ValueError("user_id is required in input_data")
            
            tenant_id = state.input_data.get("tenant_id")
            if not tenant_id:
                tenant_id = state.tenant_id
            if not tenant_id:
                raise ValueError("tenant_id is required in state")
            
            db = get_tenant_session(tenant_id)

            report_type = state.input_data.get("report_type", "weekly")
            period_start = state.input_data.get("period_start")
            period_end = state.input_data.get("period_end")

            # Set default period if not provided (last week for weekly report)
            if not period_start or not period_end:
                today = date.today()
                if report_type == "weekly":
                    period_start = today - timedelta(days=today.weekday() + 7)
                    period_end = today - timedelta(days=today.weekday() + 1)
                elif report_type == "monthly":
                    # Fix: Properly calculate last month dates
                    first_day_this_month = today.replace(day=1)
                    last_day_prev_month = first_day_this_month - timedelta(days=1)
                    _, days_in_prev_month = monthrange(last_day_prev_month.year, last_day_prev_month.month)
                    period_start = last_day_prev_month.replace(day=1)
                    period_end = last_day_prev_month.replace(day=min(days_in_prev_month, last_day_prev_month.day))
                else:
                    # Default to last 30 days
                    period_end = today
                    period_start = today - timedelta(days=30)

            db.begin()
            
            # 1. Generate financial report
            report_data = self._generate_financial_report(db, user_id, period_start, period_end, report_type, state.input_data.get("forecast", False))
            
            # 2. Save report to database
            report_record = self._save_report(db, user_id, tenant_id, report_type, period_start, period_end, report_data)
            
            # 3. Check for alerts
            alerts = self._check_alerts(db, user_id)
            
            db.commit()

            # 4. Send alerts if needed (outside transaction)
            if alerts:
                self._send_alerts(alerts)

            state.output_data["report_id"] = report_record.id if report_record else None
            state.output_data["report_data"] = report_data
            state.output_data["alerts"] = alerts
            state.output_data["status"] = "reporting_completed"
            state.output_data["processed_at"] = datetime.utcnow().isoformat()

            logger.info(f"ReporterAgent completed: report generated, {len(alerts)} alerts")
            return state

        except Exception as e:
            logger.error(f"ReporterAgent failed: {str(e)}")
            if db:
                db.rollback()
            state.error = str(e)
            state.output_data["status"] = "failed"
            return state
        finally:
            if db:
                db.close()

    def _generate_financial_report(
        self, 
        db: SessionLocal, 
        user_id: int, 
        period_start: date, 
        period_end: date, 
        report_type: str,
        forecast: bool = False
    ) -> Dict[str, Any]:
        """
        Generate a financial report for the given period.

        Returns:
            Dictionary containing report data
        """
        # Use utility function to generate report
        report_data = generate_financial_report(
            db=db,
            user_id=user_id,
            period_start=period_start,
            period_end=period_end,
            report_type=report_type,
            forecast=forecast
        )
        return report_data

    def _save_report(
        self, 
        db: SessionLocal, 
        user_id: int,
        tenant_id: int,
        report_type: str, 
        period_start: date, 
        period_end: date, 
        report_data: Dict[str, Any]
    ) -> Optional[Report]:
        """
        Save the generated report to the database.

        Returns:
            Report object or None if failed
        """
        try:
            report = Report(
                report_type=report_type,
                title=f"{report_type.capitalize()} Financial Report {period_start} to {period_end}",
                content=report_data,
                tenant_id=tenant_id,
                period_start=period_start,
                period_end=period_end
            )
            db.add(report)
            db.commit()
            db.refresh(report)
            return report
        except Exception as e:
            logger.error(f"Failed to save report: {str(e)}")
            db.rollback()
            return None

    def _check_alerts(self, db: SessionLocal, user_id: int) -> List[Dict[str, Any]]:
        """
        Check for alert conditions (overdue amounts, unusual spending, etc.).

        Returns:
            List of alert dictionaries
        """
        alerts = []
        
        # Use utility function to check alert conditions
        alerts = check_alert_conditions(db, user_id)
        
        return alerts

    def _send_alerts(self, alerts: List[Dict[str, Any]]) -> None:
        """
        Send alerts via email, SMS, or other channels.

        Args:
            alerts: List of alert dictionaries to send
        """
        for alert in alerts:
            try:
                # Use utility function to send alert
                send_alert(alert)
                logger.info(f"Sent alert: {alert.get('title', 'Unknown alert')}")
            except Exception as e:
                logger.error(f"Failed to send alert: {str(e)}")


# Example tool implementations
class GenerateReportTool(BaseTool):
    name: str = "generate_report"
    description: str = "Generate a financial report for a given period"
    args_schema: type[BaseModel] = GenerateReportInput

    def _run(self, report_type: str, period_start: date, period_end: date, user_id: int) -> str:
        # In a real implementation, this would trigger report generation
        return f"Generated {report_type} report for user {user_id} from {period_start} to {period_end}"

    async def _arun(self, report_type: str, period_start: date, period_end: date, user_id: int) -> str:
        return self._run(report_type, period_start, period_end, user_id)


class ExportReportTool(BaseTool):
    name: str = "export_report"
    description: str = "Export a report to a specified format"
    args_schema: type[BaseModel] = ExportReportInput

    def _run(self, report_id: int, format: str) -> str:
        # In a real implementation, this would export the report
        return f"Exported report {report_id} to {format} format"

    async def _arun(self, report_id: int, format: str) -> str:
        return self._run(report_id, format)


class CheckAlertsTool(BaseTool):
    name: str = "check_alerts"
    description: str = "Check for alert conditions (overdue, unusual spending, etc.)"
    args_schema: type[BaseModel] = CheckAlertsInput

    def _run(self, user_id: int) -> str:
        # In a real implementation, this would check alert conditions
        return f"Checked alerts for user {user_id}"

    async def _arun(self, user_id: int) -> str:
        return self._run(user_id)