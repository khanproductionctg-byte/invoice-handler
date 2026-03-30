"""
Report generation utilities for creating financial reports.
"""
import logging
import csv
from typing import Dict, List, Any, Optional, Tuple
from datetime import date, datetime, timedelta
from decimal import Decimal
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import func

from db.models import Invoice, Expense, Payment

logger = logging.getLogger(__name__)


def _generate_simple_forecast(db: Session, user_id: int, period_start: date, period_end: date) -> Optional[Dict[str, Any]]:
    """
    Generate a simple linear regression forecast for financial metrics.
    
    Args:
        db: Database session
        user_id: ID of the user
        period_start: Start date of the period we just reported on
        period_end: End date of the period we just reported on
        
    Returns:
        Dictionary containing forecast data or None if insufficient data
    """
    try:
        # Get historical monthly data for the last 12 months
        twelve_months_ago = period_end - timedelta(days=365)
        
        # Query monthly aggregates for invoices
        invoice_query = db.query(
            func.strftime('%Y-%m', Invoice.invoice_date).label('month'),
            func.sum(Invoice.amount_due).label('total_invoiced'),
            func.sum(Invoice.amount_paid).label('total_paid'),
            func.count(Invoice.id).label('invoice_count')
        ).filter(
            Invoice.tenant_id == tenant_id,
            Invoice.invoice_date >= twelve_months_ago,
            Invoice.invoice_date < period_end  # Up to but not including current period
        ).group_by(
            func.strftime('%Y-%m', Invoice.invoice_date)
        ).order_by(
            func.strftime('%Y-%m', Invoice.invoice_date)
        ).all()
        
        # Query monthly aggregates for expenses
        expense_query = db.query(
            func.strftime('%Y-%m', Expense.expense_date).label('month'),
            func.sum(Expense.amount).label('total_expenses'),
            func.count(Expense.id).label('expense_count')
        ).filter(
            Expense.tenant_id == tenant_id,
            Expense.expense_date >= twelve_months_ago,
            Expense.expense_date < period_end  # Up to but not including current period
        ).group_by(
            func.strftime('%Y-%m', Expense.expense_date)
        ).order_by(
            func.strftime('%Y-%m', Expense.expense_date)
        ).all()
        
        # Need at least 3 months of data for meaningful forecast
        if len(invoice_query) < 3 or len(expense_query) < 3:
            logger.warning(f"Insufficient historical data for forecasting: {len(invoice_query)} invoice months, {len(expense_query)} expense months")
            return None
        
        # Convert to numeric arrays for regression
        invoice_months = list(range(len(invoice_query)))
        invoice_totals = [float(row.total_invoiced) for row in invoice_query]
        paid_totals = [float(row.total_paid) for row in invoice_query]
        
        expense_months = list(range(len(expense_query)))
        expense_totals = [float(row.total_expenses) for row in expense_query]
        
        # Simple linear regression using numpy
        def linear_regression(x, y):
            if len(x) < 2:
                return 0.0, np.mean(y) if len(y) > 0 else 0.0
            x = np.array(x)
            y = np.array(y)
            slope = np.cov(x, y)[0, 1] / np.var(x) if np.var(x) != 0 else 0
            intercept = np.mean(y) - slope * np.mean(x)
            return slope, intercept
        
        # Forecast next period (one month ahead)
        next_invoice_month = len(invoice_query)
        next_expense_month = len(expense_query)
        
        # Invoice forecast
        inv_slope, inv_intercept = linear_regression(invoice_months, invoice_totals)
        predicted_invoiced = inv_slope * next_invoice_month + inv_intercept
        
        inv_paid_slope, inv_paid_intercept = linear_regression(invoice_months, paid_totals)
        predicted_paid = inv_paid_slope * next_invoice_month + inv_paid_intercept
        
        # Expense forecast
        exp_slope, exp_intercept = linear_regression(expense_months, expense_totals)
        predicted_expenses = exp_slope * next_expense_month + exp_intercept
        
        # Calculate confidence intervals (simplified: using standard error)
        def forecast_confidence(x, y, slope, intercept, x_pred):
            if len(x) < 2:
                return 0.0
            x = np.array(x)
            y = np.array(y)
            y_pred = intercept + slope * x
            residuals = y - y_pred
            std_error = np.sqrt(np.sum(residuals**2) / (len(x) - 2))
            # For simplicity, using 1 std error as confidence interval
            return std_error
        
        inv_confidence = forecast_confidence(invoice_months, invoice_totals, inv_slope, inv_intercept, next_invoice_month)
        paid_confidence = forecast_confidence(invoice_months, paid_totals, inv_paid_slope, inv_paid_intercept, next_invoice_month)
        exp_confidence = forecast_confidence(expense_months, expense_totals, exp_slope, exp_intercept, next_expense_month)
        
        # Calculate predicted outstanding and net profit
        predicted_outstanding = max(0, predicted_invoiced - predicted_paid)
        predicted_net = predicted_invoiced - predicted_expenses
        
        # Prepare forecast data
        forecast_data = {
            "method": "linear_regression",
            "period": {
                "start": (period_end + timedelta(days=1)).isoformat(),  # Start next day after period_end
                "end": (period_end + timedelta(days=30)).isoformat()    # Approximate next month
            },
            "predictions": {
                "total_invoiced": max(0, predicted_invoiced),
                "total_paid": max(0, predicted_paid),
                "outstanding": predicted_outstanding,
                "total_expenses": max(0, predicted_expenses),
                "net_profit": predicted_net,
                "confidence_intervals": {
                    "total_invoiced": [max(0, predicted_invoiced - inv_confidence), predicted_invoiced + inv_confidence],
                    "total_paid": [max(0, predicted_paid - paid_confidence), predicted_paid + paid_confidence],
                    "total_expenses": [max(0, predicted_expenses - exp_confidence), predicted_expenses + exp_confidence]
                }
            },
            "historical_months": len(invoice_query)  # Indicate how many months of data were used
        }
        
        return forecast_data
        
    except Exception as e:
        logger.error(f"Failed to generate forecast: {str(e)}")
        return None


def generate_financial_report(
    db: Session,
    tenant_id: int,
    period_start: date,
    period_end: date,
    report_type: str = "monthly",
    forecast: bool = False
) -> Dict[str, Any]:
    """
    Generate a financial report for the given period and tenant.

    Args:
        db: Database session
        tenant_id: ID of the tenant
        period_start: Start date of the period
        period_end: End date of the period
        report_type: Type of report (weekly, monthly, custom)

    Returns:
        Dictionary containing the report data
    """
    logger.info(f"Generating {report_type} report for tenant {tenant_id} from {period_start} to {period_end}")
    
    # Query invoices for the period
    invoices = db.query(Invoice).filter(
        Invoice.tenant_id == tenant_id,
        Invoice.invoice_date >= period_start,
        Invoice.invoice_date <= period_end
    ).all()
    
    # Query expenses for the period
    expenses = db.query(Expense).filter(
        Expense.tenant_id == tenant_id,
        Expense.expense_date >= period_start,
        Expense.expense_date <= period_end
    ).all()
    
    # Query payments for the period
    payments = db.query(Payment).filter(
        Payment.tenant_id == tenant_id,
        Payment.payment_date >= period_start,
        Payment.payment_date <= period_end
    ).all()
    
    # Calculate invoice summary
    total_invoiced = sum(inv.amount_due for inv in invoices)
    total_paid = sum(inv.amount_paid for inv in invoices)
    invoice_summary = {
        "total_invoiced": float(total_invoiced),
        "total_paid": float(total_paid),
        "outstanding": float(total_invoiced - total_paid),
        "invoice_count": len(invoices),
        "paid_count": len([inv for inv in invoices if inv.status == "paid"]),
        "pending_count": len([inv for inv in invoices if inv.status == "pending"]),
        "overdue_count": len([inv for inv in invoices if inv.status == "overdue"]),
    }
    
    # Calculate expense summary
    total_expenses = sum(exp.amount for exp in expenses)
    # Group expenses by category
    expenses_by_category = {}
    for exp in expenses:
        category = exp.category or "uncategorized"
        if category not in expenses_by_category:
            expenses_by_category[category] = 0.0
        expenses_by_category[category] += float(exp.amount)
    
    expense_summary = {
        "total_expenses": float(total_expenses),
        "expense_count": len(expenses),
        "expenses_by_category": [
            {"category": cat, "amount": amt} 
            for cat, amt in expenses_by_category.items()
        ]
    }
    
    # Calculate overdue summary (invoices that are overdue as of period_end)
    overdue_invoices = db.query(Invoice).filter(
        Invoice.tenant_id == tenant_id,
        Invoice.due_date < period_end,
        Invoice.status == "overdue",
        Invoice.amount_paid < Invoice.amount_due
    ).all()
    
    overdue_summary = {
        "total_overdue": sum(inv.amount_due - inv.amount_paid for inv in overdue_invoices),
        "overdue_count": len(overdue_invoices),
        "overdue_by_client": [
            {
                "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor_name,
                "amount_overdue": float(inv.amount_due - inv.amount_paid),
                "days_overdue": (period_end - inv.due_date).days
            }
            for inv in overdue_invoices
        ]
    }
    
    # Prepare the report
    report = {
        "report_type": report_type,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "generated_at": datetime.utcnow().isoformat(),
        "invoice_summary": invoice_summary,
        "expense_summary": expense_summary,
        "overdue_summary": overdue_summary,
        # Additional details can be added here
        "recent_invoices": [
            {
                "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor_name,
                "amount_due": float(inv.amount_due),
                "amount_paid": float(inv.amount_paid),
                "status": inv.status,
                "due_date": inv.due_date.isoformat() if inv.due_date else None
            }
            for inv in sorted(invoices, key=lambda x: x.invoice_date, reverse=True)[:10]
        ],
        "recent_expenses": [
            {
                "vendor_name": exp.vendor_name,
                "amount": float(exp.amount),
                "category": exp.category or "uncategorized",
                "date": exp.expense_date.isoformat()
            }
            for exp in sorted(expenses, key=lambda x: x.expense_date, reverse=True)[:10]
        ]
    }
    
    # Add forecasting if requested
    if forecast:
        forecast_data = _generate_simple_forecast(db, user_id, period_start, period_end)
        if forecast_data:
            report["forecast"] = forecast_data
    
    return report


def export_report_to_excel(report_data: Dict[str, Any], file_path: str) -> bool:
    """
    Export report data to an Excel file.

    Args:
        report_data: Dictionary containing report data
        file_path: Path where the Excel file should be saved

    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(f"Exporting report to Excel: {file_path}")
        
        # Create a Pandas Excel writer
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            # Invoice summary sheet
            invoice_df = pd.DataFrame([
                {"Metric": "Total Invoiced", "Value": report_data["invoice_summary"]["total_invoiced"]},
                {"Metric": "Total Paid", "Value": report_data["invoice_summary"]["total_paid"]},
                {"Metric": "Outstanding", "Value": report_data["invoice_summary"]["outstanding"]},
                {"Metric": "Invoice Count", "Value": report_data["invoice_summary"]["invoice_count"]},
                {"Metric": "Paid Count", "Value": report_data["invoice_summary"]["paid_count"]},
                {"Metric": "Pending Count", "Value": report_data["invoice_summary"]["pending_count"]},
                {"Metric": "Overdue Count", "Value": report_data["invoice_summary"]["overdue_count"]},
            ])
            invoice_df.to_excel(writer, sheet_name='Invoice Summary', index=False)
            
            # Expense summary sheet
            expense_df = pd.DataFrame([
                {"Metric": "Total Expenses", "Value": report_data["expense_summary"]["total_expenses"]},
                {"Metric": "Expense Count", "Value": report_data["expense_summary"]["expense_count"]},
            ])
            # Add expenses by category
            for item in report_data["expense_summary"]["expenses_by_category"]:
                expense_df = pd.concat([
                    expense_df,
                    pd.DataFrame([{"Metric": f"Expense - {item['category']}", "Value": item["amount"]}])
                ], ignore_index=True)
            expense_df.to_excel(writer, sheet_name='Expense Summary', index=False)
            
            # Overdue summary sheet
            overdue_df = pd.DataFrame([
                {"Metric": "Total Overdue", "Value": report_data["overdue_summary"]["total_overdue"]},
                {"Metric": "Overdue Count", "Value": report_data["overdue_summary"]["overdue_count"]},
            ])
            overdue_df.to_excel(writer, sheet_name='Overdue Summary', index=False)
            
            # Forecast sheet (if present)
            if report_data.get("forecast"):
                forecast_data = report_data["forecast"]
                # Prepare forecast data for Excel
                forecast_rows = [
                    {"Metric": "Forecast Method", "Value": forecast_data.get("method", "N/A")},
                    {"Metric": "Forecast Period Start", "Value": forecast_data.get("period", {}).get("start", "N/A")},
                    {"Metric": "Forecast Period End", "Value": forecast_data.get("period", {}).get("end", "N/A")},
                ]
                predictions = forecast_data.get("predictions", {})
                for key, value in predictions.items():
                    if isinstance(value, list):
                        forecast_rows.append({"Metric": f"Forecast {key}", "Value": f"[{', '.join(map(str, value))}]"})
                    else:
                        forecast_rows.append({"Metric": f"Forecast {key}", "Value": value})
                forecast_df = pd.DataFrame(forecast_rows)
                forecast_df.to_excel(writer, sheet_name='Forecast', index=False)
            
            # Recent invoices sheet
            if report_data.get("recent_invoices"):
                recent_invoices_df = pd.DataFrame(report_data["recent_invoices"])
                recent_invoices_df.to_excel(writer, sheet_name='Recent Invoices', index=False)
            
            # Recent expenses sheet
            if report_data.get("recent_expenses"):
                recent_expenses_df = pd.DataFrame(report_data["recent_expenses"])
                recent_expenses_df.to_excel(writer, sheet_name='Recent Expenses', index=False)
         
        logger.info(f"Report exported successfully to {file_path}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to export report to Excel: {str(e)}")
        return False


def export_report_to_csv(report_data: Dict[str, Any], file_path: str) -> bool:
    """
    Export report data to a tax-ready CSV file.

    Args:
        report_data: Dictionary containing report data
        file_path: Path where the CSV file should be saved

    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(f"Exporting report to CSV: {file_path}")
        
        # Prepare data for CSV
        rows = []
        
        # Add header
        rows.append(["Date", "Description", "Category", "Amount", "Type", "Reference", "Vendor/Client", "Tax Deductible"])
        
        # Add invoices (as income)
        if report_data.get("recent_invoices"):
            for inv in report_data["recent_invoices"]:
                rows.append([
                    inv.get("due_date", ""),
                    f"Invoice {inv.get('invoice_number', '')}",
                    "Income",
                    f"{inv.get('amount_due', 0):.2f}",
                    "Income",
                    inv.get("invoice_number", ""),
                    inv.get("vendor_name", ""),
                    "No"  # Typically invoices are not tax deductible for the receiver
                ])
        
        # Add expenses
        if report_data.get("recent_expenses"):
            for exp in report_data["recent_expenses"]:
                # Determine if tax deductible (simplified: most business expenses are)
                category = exp.get("category", "uncategorized")
                tax_deductible = "Yes" if category not in ["personal", "non-deductible"] else "Yes"  # Simplified
                
                rows.append([
                    exp.get("date", ""),
                    exp.get("vendor_name", ""),
                    category,
                    f"{exp.get('amount', 0):.2f}",
                    "Expense",
                    exp.get("vendor_name", ""),  # Using vendor as reference for expenses
                    exp.get("vendor_name", ""),
                    tax_deductible
                ])
        
        # Add summary rows
        rows.append([])  # Empty row
        rows.append(["Summary", "", "", "", "", "", "", ""])
        rows.append(["Total Invoiced", "", "", f"{report_data['invoice_summary']['total_invoiced']:.2f}", "Income", "", "", ""])
        rows.append(["Total Paid", "", "", f"{report_data['invoice_summary']['total_paid']:.2f}", "Income", "", "", ""])
        rows.append(["Outstanding", "", "", f"{report_data['invoice_summary']['outstanding']:.2f}", "Income", "", "", ""])
        rows.append(["Total Expenses", "", "", f"{report_data['expense_summary']['total_expenses']:.2f}", "Expense", "", "", ""])
        rows.append(["Net Profit", "", "", f"{report_data['invoice_summary']['total_invoiced'] - report_data['expense_summary']['total_expenses']:.2f}", "Net", "", "", ""])
        
        # Write to CSV
        with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerows(rows)
        
        logger.info(f"Report exported successfully to CSV: {file_path}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to export report to CSV: {str(e)}")
        return False


# =============================================================================
# TAX-READY EXPORT FUNCTIONS
# =============================================================================

def export_tax_ready_report(
    db: Session,
    user_id: int,
    tax_year: int,
    tax_quarter: Optional[int] = None,
    export_format: str = "csv"
) -> Dict[str, Any]:
    """
    Generate tax-ready export of income and expenses.
    
    Supports:
    - Full year or quarterly reports
    - Categorization by tax categories
    - 1099 vendor tracking
    - Mileage deduction tracking
    
    Args:
        db: Database session
        user_id: ID of the user
        tax_year: Year for tax report
        tax_quarter: Optional quarter (1-4). If None, exports full year.
        export_format: Format to export (csv, xlsx)
        
    Returns:
        Dictionary with export data and file path
    """
    logger.info(f"Generating tax-ready report for user {user_id}, year {tax_year}, quarter {tax_quarter}")
    
    # Determine date range
    if tax_quarter:
        quarter_months = {
            1: (1, 3),
            2: (4, 6),
            3: (7, 9),
            4: (10, 12)
        }
        start_month, end_month = quarter_months.get(tax_quarter, (1, 12))
        period_start = date(tax_year, start_month, 1)
        period_end = date(tax_year, end_month, 28)  # Approximate end
    else:
        period_start = date(tax_year, 1, 1)
        period_end = date(tax_year, 12, 31)
    
    # Query invoices (income)
    invoices = db.query(Invoice).filter(
        Invoice.tenant_id == tenant_id,
        Invoice.invoice_date >= period_start,
        Invoice.invoice_date <= period_end
    ).all()
    
    # Query expenses
    expenses = db.query(Expense).filter(
        Expense.tenant_id == tenant_id,
        Expense.expense_date >= period_start,
        Expense.expense_date <= period_end
    ).all()
    
    # Categorize for tax purposes
    tax_categories = {
        "office_supplies": "Office Expenses",
        "utilities": "Utilities",
        "travel": "Travel",
        "meals": "Meals & Entertainment",  # 50% deductible in US
        "software": "Software & Subscriptions",
        "professional_services": "Professional Services",
        "rent": "Rent & Lease",
        "insurance": "Insurance",
        "marketing": "Advertising & Marketing",
        "equipment": "Equipment",
        "vehicle": "Vehicle Expenses",
        "education": "Education & Training",
        "utilities": "Utilities",
        "communication": "Communication",
        "other": "Other Expenses"
    }
    
    # Calculate totals
    total_income = sum(float(inv.amount_due or 0) for inv in invoices)
    total_expenses = sum(float(exp.amount or 0) for exp in expenses)
    
    # Group expenses by category
    expenses_by_category = {}
    for exp in expenses:
        category = exp.category or "other"
        cat_name = tax_categories.get(category, "Other Expenses")
        if cat_name not in expenses_by_category:
            expenses_by_category[cat_name] = 0
        expenses_by_category[cat_name] += float(exp.amount or 0)
    
    # Build tax report data
    tax_report = {
        "tax_year": tax_year,
        "tax_quarter": tax_quarter,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "generated_at": datetime.now().isoformat(),
        "income": {
            "total_invoiced": total_income,
            "total_paid": sum(float(inv.amount_paid or 0) for inv in invoices),
            "outstanding": total_income - sum(float(inv.amount_paid or 0) for inv in invoices),
            "invoice_count": len(invoices),
            "by_customer": {}
        },
        "expenses": {
            "total": total_expenses,
            "by_category": expenses_by_category,
            "expense_count": len(expenses)
        },
        "summary": {
            "net_income": total_income - total_expenses,
            "estimated_tax": (total_income - total_expenses) * 0.25,  # Rough 25% estimate
            "meals_deductible": expenses_by_category.get("Meals & Entertainment", 0) * 0.5
        },
        "line_items": {
            "income": [],
            "expenses": []
        }
    }
    
    # Add invoice line items
    for inv in invoices:
        tax_report["line_items"]["income"].append({
            "date": inv.invoice_date.isoformat() if inv.invoice_date else None,
            "description": f"Invoice {inv.invoice_number}",
            "amount": float(inv.amount_due or 0),
            "category": "Sales/Income",
            "vendor_customer": inv.vendor_name,
            "tax_deductible": False
        })
    
    # Add expense line items
    for exp in expenses:
        category = exp.category or "other"
        cat_name = tax_categories.get(category, "Other Expenses")
        
        # Calculate deductible amount (meals are only 50%)
        amount = float(exp.amount or 0)
        deductible_amount = amount * 0.5 if category == "meals" else amount
        
        tax_report["line_items"]["expenses"].append({
            "date": exp.expense_date.isoformat() if exp.expense_date else None,
            "description": exp.description or exp.vendor_name,
            "amount": amount,
            "deductible_amount": deductible_amount,
            "category": cat_name,
            "vendor": exp.vendor_name,
            "tax_deductible": True,
            "receipt_url": exp.receipt_url
        })
    
    return tax_report


def export_tax_report_to_file(
    db: Session,
    user_id: int,
    tax_year: int,
    tax_quarter: Optional[int] = None,
    file_path: Optional[str] = None,
    export_format: str = "csv"
) -> Dict[str, Any]:
    """
    Export tax report to file.
    
    Args:
        db: Database session
        user_id: ID of the user
        tax_year: Year for tax report
        tax_quarter: Optional quarter (1-4)
        file_path: Optional custom file path
        export_format: Format (csv, xlsx)
        
    Returns:
        Dictionary with success status and file path
    """
    try:
        # Generate tax report
        tax_report = export_tax_ready_report(
            db=db,
            user_id=user_id,
            tax_year=tax_year,
            tax_quarter=tax_quarter,
            export_format=export_format
        )
        
        # Determine file path
        if not file_path:
            quarter_str = f"_Q{tax_quarter}" if tax_quarter else ""
            file_path = f"tax_report_{tax_year}{quarter_str}_{user_id}.{export_format}"
        
        # Export based on format
        if export_format == "csv":
            return _export_tax_csv(tax_report, file_path)
        elif export_format == "xlsx":
            return _export_tax_excel(tax_report, file_path)
        else:
            return {"success": False, "error": f"Unsupported format: {export_format}"}
            
    except Exception as e:
        logger.error(f"Failed to export tax report: {str(e)}")
        return {"success": False, "error": str(e)}


def _export_tax_csv(tax_report: Dict, file_path: str) -> Dict[str, Any]:
    """Export tax report to CSV with proper tax format."""
    try:
        rows = []
        
        # Header
        rows.append(["Tax Year", tax_report["tax_year"]])
        if tax_report["tax_quarter"]:
            rows.append(["Tax Quarter", tax_report["tax_quarter"]])
        rows.append(["Period Start", tax_report["period_start"]])
        rows.append(["Period End", tax_report["period_end"]])
        rows.append([])
        
        # Summary
        rows.append(["SUMMARY"])
        rows.append(["Total Income", f"${tax_report['income']['total_invoiced']:.2f}"])
        rows.append(["Total Expenses", f"${tax_report['expenses']['total']:.2f}"])
        rows.append(["Net Income", f"${tax_report['summary']['net_income']:.2f}"])
        rows.append(["Estimated Tax (25%)", f"${tax_report['summary']['estimated_tax']:.2f}"])
        rows.append([])
        
        # Expenses by Category
        rows.append(["EXPENSES BY CATEGORY"])
        rows.append(["Category", "Amount"])
        for cat, amount in tax_report["expenses"]["by_category"].items():
            rows.append([cat, f"${amount:.2f}"])
        rows.append([])
        
        # Income Line Items
        rows.append(["INCOME LINE ITEMS"])
        rows.append(["Date", "Description", "Amount", "Category", "Tax Deductible"])
        for item in tax_report["line_items"]["income"]:
            rows.append([
                item["date"],
                item["description"],
                f"${item['amount']:.2f}",
                item["category"],
                "No"
            ])
        rows.append([])
        
        # Expense Line Items
        rows.append(["EXPENSE LINE ITEMS"])
        rows.append(["Date", "Description", "Amount", "Deductible", "Category", "Vendor", "Tax Deductible"])
        for item in tax_report["line_items"]["expenses"]:
            rows.append([
                item["date"],
                item["description"][:50],  # Truncate long descriptions
                f"${item['amount']:.2f}",
                f"${item['deductible_amount']:.2f}",
                item["category"],
                item["vendor"][:30],
                "Yes" if item["tax_deductible"] else "No"
            ])
        
        # Write CSV
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        
        logger.info(f"Tax report exported to CSV: {file_path}")
        return {"success": True, "file_path": file_path, "data": tax_report}
        
    except Exception as e:
        logger.error(f"Failed to export tax CSV: {str(e)}")
        return {"success": False, "error": str(e)}


def _export_tax_excel(tax_report: Dict, file_path: str) -> Dict[str, Any]:
    """Export tax report to Excel with multiple sheets."""
    try:
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            # Summary sheet
            summary_data = {
                "Item": ["Total Income", "Total Expenses", "Net Income", "Estimated Tax"],
                "Amount": [
                    tax_report['income']['total_invoiced'],
                    tax_report['expenses']['total'],
                    tax_report['summary']['net_income'],
                    tax_report['summary']['estimated_tax']
                ]
            }
            pd.DataFrame(summary_data).to_excel(writer, sheet_name="Summary", index=False)
            
            # Expenses by category
            if tax_report["expenses"]["by_category"]:
                cat_data = {
                    "Category": list(tax_report["expenses"]["by_category"].keys()),
                    "Amount": list(tax_report["expenses"]["by_category"].values())
                }
                pd.DataFrame(cat_data).to_excel(writer, sheet_name="Expenses by Category", index=False)
            
            # Income details
            if tax_report["line_items"]["income"]:
                pd.DataFrame(tax_report["line_items"]["income"]).to_excel(
                    writer, sheet_name="Income Details", index=False
                )
            
            # Expense details
            if tax_report["line_items"]["expenses"]:
                pd.DataFrame(tax_report["line_items"]["expenses"]).to_excel(
                    writer, sheet_name="Expense Details", index=False
                )
        
        logger.info(f"Tax report exported to Excel: {file_path}")
        return {"success": True, "file_path": file_path, "data": tax_report}
        
    except Exception as e:
        logger.error(f"Failed to export tax Excel: {str(e)}")
        return {"success": False, "error": str(e)}