"""
API routes for report generation and export - WITH TENANT ISOLATION.
All endpoints filter by tenant_id to ensure data isolation.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
import os
import tempfile
from datetime import date

from db.database import get_db
from db import models
from schemas import report as report_schema
from utils.report_generator import export_report_to_excel, export_report_to_csv
from middleware import get_current_tenant

# Optional Celery tasks - only import if Celery is available
try:
    from worker.tasks.report_tasks import generate_weekly_report, generate_monthly_report, export_report_to_format
    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False
    generate_weekly_report = None
    generate_monthly_report = None
    export_report_to_format = None

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/", response_model=report_schema.Report)
def create_report(
    report: report_schema.ReportCreate,
    background_tasks: BackgroundTasks,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Generate a new financial report for the current tenant.
    """
    db_report = models.Report(
        report_type=report.report_type,
        title=report.title,
        content=report.content,
        tenant_id=tenant.id
    )
    db.add(db_report)
    db.commit()
    db.refresh(db_report)
    return db_report


@router.get("/", response_model=list[report_schema.Report])
def read_reports(
    skip: int = 0,
    limit: int = 100,
    report_type: Optional[str] = None,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Retrieve reports for the current tenant only.
    Filters by tenant_id to ensure data isolation.
    """
    query = db.query(models.Report).filter(
        models.Report.tenant_id == tenant.id
    )
    
    if report_type:
        query = query.filter(models.Report.report_type == report_type)
    
    reports = query.order_by(models.Report.created_at.desc()).offset(skip).limit(limit).all()
    return reports


@router.get("/{report_id}", response_model=report_schema.Report)
def read_report(
    report_id: int,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Retrieve a specific report by ID.
    Only returns if the report belongs to the current tenant.
    """
    report = db.query(models.Report).filter(
        models.Report.id == report_id,
        models.Report.tenant_id == tenant.id
    ).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.post("/{report_id}/generate-weekly")
def generate_weekly_report_endpoint(
    report_id: int,
    forecast: bool = Query(False, description="Include forecasting in the report"),
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Generate a weekly report for the current tenant.
    """
    if not CELERY_AVAILABLE or generate_weekly_report is None:
        raise HTTPException(
            status_code=503, 
            detail="Celery is not available. Install celery to use this feature."
        )
    
    # Get the report to verify it exists AND belongs to this tenant
    report = db.query(models.Report).filter(
        models.Report.id == report_id,
        models.Report.tenant_id == tenant.id
    ).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Trigger Celery task to generate weekly report
    task = generate_weekly_report.delay(tenant.id, forecast)
    
    return {
        "message": f"Weekly report generation started for report {report_id}",
        "task_id": task.id,
        "forecast_included": forecast
    }


@router.post("/{report_id}/generate-monthly")
def generate_monthly_report_endpoint(
    report_id: int,
    forecast: bool = Query(False, description="Include forecasting in the report"),
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Generate a monthly report for the current tenant.
    """
    if not CELERY_AVAILABLE or generate_monthly_report is None:
        raise HTTPException(
            status_code=503, 
            detail="Celery is not available. Install celery to use this feature."
        )
    
    # Get the report to verify it exists AND belongs to this tenant
    report = db.query(models.Report).filter(
        models.Report.id == report_id,
        models.Report.tenant_id == tenant.id
    ).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Trigger Celery task to generate monthly report
    task = generate_monthly_report.delay(tenant.id, forecast)
    
    return {
        "message": f"Monthly report generation started for report {report_id}",
        "task_id": task.id,
        "forecast_included": forecast
    }


@router.post("/{report_id}/export")
def export_report_endpoint(
    report_id: int,
    format: str = Query(..., pattern="^(csv|excel|pdf)$", description="Export format"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Export a report to the specified format.
    Only allows exporting reports belonging to the current tenant.
    """
    # Get the report ONLY if it belongs to this tenant
    report = db.query(models.Report).filter(
        models.Report.id == report_id,
        models.Report.tenant_id == tenant.id
    ).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Validate format
    if format not in ["csv", "excel", "pdf"]:
        raise HTTPException(status_code=400, detail="Invalid format. Supported formats: csv, excel, pdf")
    
    # For CSV and Excel, we can generate immediately
    if format in ["csv", "excel"]:
        try:
            # Create temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{format}") as tmp_file:
                temp_path = tmp_file.name
            
            # Export report
            if format == "csv":
                success = export_report_to_csv(report.content, temp_path)
            else:  # excel
                success = export_report_to_excel(report.content, temp_path)
            
            if not success:
                raise HTTPException(status_code=500, detail="Failed to export report")
            
            # Return file
            def iterfile():
                with open(temp_path, mode="rb") as file_like:
                    yield from file_like
                # Clean up temp file after sending
                os.unlink(temp_path)
            
            media_type = {
                "csv": "text/csv",
                "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            }[format]
            
            filename = f"report_{report_id}_{date.today().isoformat()}.{format}"
            
            return StreamingResponse(
                iterfile(),
                media_type=media_type,
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")
    else:
        # For PDF or other formats that might need background processing
        if not CELERY_AVAILABLE or export_report_to_format is None:
            raise HTTPException(
                status_code=503, 
                detail="Celery is not available. Only CSV and Excel exports are supported without Celery."
            )
        # Trigger Celery task for export
        task = export_report_to_format.delay(report_id, format)
        return {
            "message": f"Report export to {format} started for report {report_id}",
            "task_id": task.id,
            "format": format
        }


@router.get("/{report_id}/download/{format}")
def download_report(
    report_id: int,
    format: str,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Download a report in the specified format (alternative endpoint).
    Only allows downloading reports belonging to the current tenant.
    """
    # Verify the report belongs to this tenant
    report = db.query(models.Report).filter(
        models.Report.id == report_id,
        models.Report.tenant_id == tenant.id
    ).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    
    raise HTTPException(
        status_code=501, 
        detail="Use POST /reports/{report_id}/export with format parameter for downloading"
    )


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(
    report_id: int,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Delete a report.
    Only allows deleting reports belonging to the current tenant.
    """
    report = db.query(models.Report).filter(
        models.Report.id == report_id,
        models.Report.tenant_id == tenant.id
    ).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    
    db.delete(report)
    db.commit()
    return None
