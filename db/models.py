from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, Numeric, Date, JSON, Index, CheckConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from db.database import Base
from decimal import Decimal
import enum


def utc_now():
    return datetime.now(timezone.utc)


class InvoiceStatus(str, enum.Enum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"


# ============================================================================
# TENANT MANAGEMENT (Multi-Tenancy)
# ============================================================================

class Tenant(Base):
    __tablename__ = "tenants"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    plan = Column(String, default="free")  # free, pro, enterprise
    
    # Lemon Squeezy fields (replacing Stripe)
    lemon_customer_id = Column(String, nullable=True)
    lemon_subscription_id = Column(String, nullable=True)
    lemon_variant_id = Column(String, nullable=True)
    subscription_status = Column(String, default="inactive")  # active, past_due, canceled, trialing
    subscription_renews_at = Column(DateTime, nullable=True)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    # Relationships
    users = relationship("TenantUser", back_populates="tenant", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="tenant", cascade="all, delete-orphan")
    expenses = relationship("Expense", back_populates="tenant", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="tenant", cascade="all, delete-orphan")
    customers = relationship("Customer", back_populates="tenant", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="tenant", cascade="all, delete-orphan")
    connected_accounts = relationship("ConnectedAccount", back_populates="tenant", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="tenant", cascade="all, delete-orphan")
    usage_records = relationship("UsageRecord", back_populates="tenant", cascade="all, delete-orphan")
    workflow_runs = relationship("WorkflowRun", back_populates="tenant", cascade="all, delete-orphan")


class TenantUser(Base):
    __tablename__ = "tenant_users"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String, default="member")  # owner, admin, member, viewer
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    
    tenant = relationship("Tenant", back_populates="users")
    user = relationship("User")


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    hashed_password = Column(String, nullable=True)  # Nullable for Clerk auth
    clerk_id = Column(String, unique=True, nullable=True)  # Clerk user ID
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    # Account lockout fields
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)
    
    # Relationships
    tenant_users = relationship("TenantUser", back_populates="user", cascade="all, delete-orphan")
    workflow_runs = relationship("WorkflowRun", back_populates="user")


class ConnectedAccount(Base):
    __tablename__ = "connected_accounts"
    __table_args__ = (
        Index('idx_connected_account_tenant_provider', 'tenant_id', 'provider'),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    provider = Column(String, nullable=False, index=True)  # google, quickbooks, xero, plaid
    provider_account_id = Column(String, nullable=False)
    # Encrypted token storage - stored as encrypted JSON
    _encrypted_token_data = Column("encrypted_tokens", Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    tenant = relationship("Tenant", back_populates="connected_accounts")
    
    # Lazy import to avoid circular imports
    _token_encryptor = None
    
    @classmethod
    def _get_encryptor(cls):
        """Get or create the token encryptor."""
        if cls._token_encryptor is None:
            from utils.token_encryption import get_token_encryptor
            cls._token_encryptor = get_token_encryptor()
        return cls._token_encryptor
    
    @property
    def access_token(self):
        """Decrypt and return access token."""
        if not self._encrypted_token_data:
            return None
        encryptor = self._get_encryptor()
        data = encryptor.decrypt(self._encrypted_token_data)
        return data.get("access_token") if data else None
    
    @access_token.setter
    def access_token(self, value):
        """Encrypt and store access token."""
        encryptor = self._get_encryptor()
        existing = {}
        if self._encrypted_token_data:
            existing = encryptor.decrypt(self._encrypted_token_data) or {}
        existing["access_token"] = value
        self._encrypted_token_data = encryptor.encrypt(existing)
    
    @property
    def refresh_token(self):
        """Decrypt and return refresh token."""
        if not self._encrypted_token_data:
            return None
        encryptor = self._get_encryptor()
        data = encryptor.decrypt(self._encrypted_token_data)
        return data.get("refresh_token") if data else None
    
    @refresh_token.setter
    def refresh_token(self, value):
        """Encrypt and store refresh token."""
        encryptor = self._get_encryptor()
        existing = {}
        if self._encrypted_token_data:
            existing = encryptor.decrypt(self._encrypted_token_data) or {}
        existing["refresh_token"] = value
        self._encrypted_token_data = encryptor.encrypt(existing)


class PlaidTransaction(Base):
    __tablename__ = "plaid_transactions"
    __table_args__ = (
        Index('idx_plaid_txn_tenant_date', 'tenant_id', 'transaction_date'),
        Index('idx_plaid_txn_account', 'account_id'),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    plaid_transaction_id = Column(String, unique=True, nullable=False, index=True)
    account_id = Column(String, nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String, default="USD")
    transaction_date = Column(Date, nullable=False, index=True)
    name = Column(String, nullable=True)
    merchant_name = Column(String, nullable=True)
    category = Column(String, nullable=True)
    pending = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class APIKey(Base):
    __tablename__ = "api_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String, nullable=False)
    key_hash = Column(String, unique=True, nullable=False)
    prefix = Column(String, nullable=False)  # First 8 chars for display
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    
    tenant = relationship("Tenant", back_populates="api_keys")


class UsageRecord(Base):
    __tablename__ = "usage_records"
    __table_args__ = (
        Index('idx_usage_tenant_month', 'tenant_id', 'month'),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    month = Column(String, nullable=False, index=True)  # "2026-03"
    invoices_processed = Column(Integer, default=0)
    invoices_limit = Column(Integer, default=0)
    emails_sent = Column(Integer, default=0)
    emails_limit = Column(Integer, default=0)
    sms_sent = Column(Integer, default=0)
    sms_limit = Column(Integer, default=0)
    api_calls = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    tenant = relationship("Tenant", back_populates="usage_records")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index('idx_workflow_tenant_status', 'tenant_id', 'status'),
        Index('idx_workflow_tenant_created', 'tenant_id', 'created_at'),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    invocation_id = Column(String, unique=True, index=True, nullable=False)
    workflow_type = Column(String, nullable=False, index=True)  # full, ingestion_only, reconciliation_only, chasing_only
    status = Column(String, default="queued", index=True)  # queued, running, completed, failed
    current_step = Column(String, nullable=True)
    progress = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    results = Column(JSON, nullable=True)
    tokens_input = Column(Integer, default=0)
    tokens_output = Column(Integer, default=0)
    estimated_cost_usd = Column(Numeric(12, 4), default=Decimal("0.0000"))
    budget_limit_usd = Column(Numeric(12, 4), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    
    tenant = relationship("Tenant", back_populates="workflow_runs")
    user = relationship("User")


# ============================================================================
# BUSINESS ENTITIES (Add tenant_id to existing models)
# ============================================================================

class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index('idx_invoice_tenant_status', 'tenant_id', 'status'),
        Index('idx_invoice_tenant_due_date', 'tenant_id', 'due_date'),
        Index('idx_invoice_tenant_date', 'tenant_id', 'invoice_date'),
        Index('idx_invoice_status', 'status'),
        Index('idx_invoice_due_date', 'due_date'),
        CheckConstraint('amount_due > 0', name='invoice_amount_positive'),
        CheckConstraint('amount_due <= 10000000', name='invoice_amount_max'),
        CheckConstraint('due_date >= CURRENT_DATE - interval \'1 year\'', name='invoice_due_not_ancient'),
        CheckConstraint('due_date <= CURRENT_DATE + interval \'5 years\'', name='invoice_due_not_future'),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    invoice_number = Column(String, index=True, nullable=False)  # Unique per tenant
    vendor_name = Column(String, nullable=False)
    vendor_id = Column(String, nullable=True)
    amount_due = Column(Numeric(10, 2), nullable=False)
    amount_paid = Column(Numeric(10, 2), default=0)
    currency = Column(String, default="USD")
    invoice_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    status = Column(String, default="pending", index=True)  # pending, paid, overdue, disputed
    description = Column(Text, nullable=True)
    line_items = Column(Text, nullable=True)
    source = Column(String, nullable=False)
    source_id = Column(String, nullable=True)
    needs_review = Column(Boolean, default=False)
    review_notes = Column(Text, nullable=True)
    reminder_count = Column(Integer, default=0)
    last_reminder_date = Column(DateTime, nullable=True)
    last_reminder_type = Column(String, nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    vendor_email = Column(String, nullable=True)
    vendor_phone = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    tenant = relationship("Tenant", back_populates="invoices")
    customer = relationship("Customer", back_populates="invoices")


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        Index('idx_customer_tenant_email', 'tenant_id', 'email'),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    email = Column(String, index=True, nullable=False)
    phone = Column(String, nullable=True)
    full_name = Column(String, nullable=True, index=True)
    company_name = Column(String, nullable=True, index=True)
    opt_out_email = Column(Boolean, default=False)
    opt_out_sms = Column(Boolean, default=False)
    preferred_language = Column(String, default="en")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    tenant = relationship("Tenant", back_populates="customers")
    invoices = relationship("Invoice", back_populates="customer")


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        Index('idx_expense_tenant_date', 'tenant_id', 'expense_date'),
        Index('idx_expense_tenant_category', 'tenant_id', 'category'),
        Index('idx_expense_category', 'category'),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    vendor_name = Column(String, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String, default="USD")
    expense_date = Column(Date, nullable=False, index=True)
    category = Column(String, nullable=True, index=True)
    description = Column(Text, nullable=True)
    receipt_url = Column(String, nullable=True)
    source = Column(String, nullable=False)
    source_id = Column(String, nullable=True)
    needs_review = Column(Boolean, default=False)
    review_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    tenant = relationship("Tenant", back_populates="expenses")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index('idx_payment_tenant_date', 'tenant_id', 'payment_date'),
        Index('idx_payment_invoice_id', 'invoice_id'),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    payment_number = Column(String, index=True, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String, default="USD")
    payment_date = Column(Date, nullable=False, index=True)
    vendor_name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True, index=True)
    source = Column(String, nullable=False)
    source_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    tenant = relationship("Tenant", back_populates="payments")
    invoice = relationship("Invoice")


class PaymentFollowup(Base):
    __tablename__ = "payment_followups"
    __table_args__ = (
        Index('idx_followup_tenant_invoice', 'tenant_id', 'invoice_id'),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    followup_type = Column(String, nullable=False)  # email, sms
    sent_at = Column(DateTime, default=utc_now, nullable=False)
    response_received = Column(Boolean, default=False)
    response_date = Column(DateTime, nullable=True)


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        Index('idx_report_tenant_type', 'tenant_id', 'report_type'),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    report_type = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    content = Column(JSON, nullable=False)
    generated_at = Column(DateTime, default=utc_now)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    is_archived = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=utc_now)
    
    tenant = relationship("Tenant", back_populates="reports")


class ReconciliationHistory(Base):
    __tablename__ = "reconciliation_history"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    idempotency_key = Column(String, unique=True, nullable=True, index=True)  # For deduplication
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)
    feature_vector = Column(String, nullable=True)  # JSON string
    outcome = Column(Integer)
    created_at = Column(DateTime, default=utc_now)
    
    tenant = relationship("Tenant")
    invoice = relationship("Invoice", foreign_keys=[invoice_id])
    payment = relationship("Payment", foreign_keys=[payment_id])


class AuditLog(Base):
    """
    Audit log for SOC 2 Type II compliance.
    Tracks all data access and modification events.
    """
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index('idx_audit_tenant_action', 'tenant_id', 'action'),
        Index('idx_audit_tenant_resource', 'tenant_id', 'resource_type', 'resource_id'),
        Index('idx_audit_tenant_created', 'tenant_id', 'created_at'),
        Index('idx_audit_user_created', 'user_id', 'created_at'),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    
    # Event details
    action = Column(String, nullable=False, index=True)  # create, read, update, delete, login, logout, export
    resource_type = Column(String, nullable=False, index=True)  # invoice, payment, customer, etc.
    resource_id = Column(Integer, nullable=True, index=True)
    
    # Request context
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    request_method = Column(String, nullable=True)
    request_path = Column(String, nullable=True)
    
    # Change details (for updates)
    old_values = Column(Text, nullable=True)  # JSON
    new_values = Column(Text, nullable=True)  # JSON
    
    # Result
    status = Column(String, nullable=False, default="success")  # success, failure
    error_message = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=utc_now, index=True)
    
    # Relationships
    tenant = relationship("Tenant")
    user = relationship("User")
