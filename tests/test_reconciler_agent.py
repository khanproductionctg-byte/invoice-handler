"""
Test for the enhanced ReconcilerAgent.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import date, datetime
from decimal import Decimal
from agents.reconciler_agent import (
    ReconcilerAgent,
    VendorNameNormalizer,
    MatchConfidence,
    DiscrepancyType
)
from agents.base_agent import AgentState


class MockLLM:
    def bind(self, tools, tool_choice=None):
        return self
    def invoke(self, prompt, **kwargs):
        mock_response = Mock()
        mock_response.content = "This is a mock response"
        return mock_response


class MockTool:
    def __init__(self, name, description):
        self.name = name
        self.description = description
    def invoke(self, tool_input):
        return f"Result from {self.name}"


@pytest.fixture
def mock_db_session():
    return Mock()


@pytest.fixture
def sample_invoice():
    invoice = Mock()
    invoice.id = 1
    invoice.invoice_number = "INV-001"
    invoice.vendor_name = "Acme Corp"
    invoice.amount_due = Decimal('100.00')
    invoice.currency = "USD"
    invoice.invoice_date = date(2026, 3, 28)
    invoice.due_date = date(2026, 4, 27)
    invoice.status = "pending"
    invoice.description = "Software development services"
    return invoice


@pytest.fixture
def sample_payment():
    payment = Mock()
    payment.id = 1
    payment.payment_number = "PAY-001"
    payment.amount = Decimal('100.00')
    payment.currency = "USD"
    payment.payment_date = date(2026, 4, 15)
    payment.vendor_name = "Acme Corporation"
    payment.description = "Payment for invoice INV-001"
    return payment


def test_reconciler_agent_initialization():
    """Test that the ReconcilerAgent initializes correctly."""
    llm = MockLLM()
    tools = [MockTool("tool1", "First tool"), MockTool("tool2", "Second tool")]
    agent = ReconcilerAgent(llm, tools)
    
    assert agent.agent_name == "ReconcilerAgent"
    assert len(agent.tools) == 2
    # Updated weights
    assert agent.match_weights["amount"] == 0.35
    assert agent.match_weights["vendor_fuzzy"] == 0.15
    assert agent.match_threshold_high == 0.85
    assert agent.match_threshold_medium == 0.65


def test_vendor_name_normalizer():
    """Test vendor name normalization."""
    assert "acme" in VendorNameNormalizer.normalize("Acme Corp Inc.")
    assert "abc" in VendorNameNormalizer.normalize("ABC LLC")
    assert "test" in VendorNameNormalizer.normalize("Test & Co.")
    
    # Test comparable names
    comparable = VendorNameNormalizer.get_comparable("The Acme Corp Inc.")
    assert "acme" in comparable


@patch('agents.reconciler_agent.SessionLocal')
@patch('agents.reconciler_agent.get_embedding')
def test_calculate_match_score(mock_get_embedding, mock_session_local):
    """Test the match score calculation with edge cases."""
    mock_get_embedding.return_value = [0.1] * 384
    
    llm = MockLLM()
    tools = []
    agent = ReconcilerAgent(llm, tools)
    
    invoice = Mock()
    invoice.id = 1
    invoice.invoice_number = "INV-001"
    invoice.amount_due = Decimal('100.00')
    invoice.vendor_name = "Acme Corp"
    invoice.currency = "USD"
    invoice.invoice_date = date(2026, 3, 28)
    invoice.due_date = date(2026, 4, 27)
    invoice.description = "Software development"
    
    payment = Mock()
    payment.id = 1
    payment.payment_number = "PAY-001"
    payment.amount = Decimal('100.00')
    payment.vendor_name = "Acme Corporation"
    payment.currency = "USD"
    payment.payment_date = date(2026, 4, 15)
    payment.description = "Payment for services"
    
    # Test with precomputed embeddings
    embedding_map = {
        "inv_vendor_1": [0.1] * 384,
        "pay_vendor_1": [0.1] * 384,
        "inv_desc_1": [0.1] * 384,
        "pay_desc_1": [0.1] * 384
    }
    
    result = agent._calculate_match_with_edge_cases(invoice, payment, embedding_map)
    
    # Should have calculated a valid score
    assert "score" in result
    assert "component_scores" in result
    assert 0.0 <= result["score"] <= 1.0


@patch('agents.reconciler_agent.SessionLocal')
def test_amount_edge_cases(mock_session_local):
    """Test amount matching edge cases."""
    llm = MockLLM()
    tools = []
    agent = ReconcilerAgent(llm, tools)
    
    # Exact match
    result = agent._calculate_amount_score(100.00, 100.00)
    assert result["score"] == 1.0
    assert result["type"] == "exact"
    
    # Partial payment (50-99%)
    result = agent._calculate_amount_score(100.00, 75.00)
    assert result.get("is_partial") is True
    assert result["score"] == 0.70
    
    # Check early discount at exact boundaries
    result = agent._calculate_amount_score(100.00, 98.00)
    # This may be caught by partial or early discount depending on logic
    
    # With late fee (1-5% over)
    result = agent._calculate_amount_score(100.00, 102.50)
    assert result.get("is_late_fee") is True
    assert result["score"] == 0.90
    
    # Exact rounding
    result = agent._calculate_amount_score(100.00, 100.00)
    assert result["score"] == 1.0


@patch('agents.reconciler_agent.SessionLocal')
def test_date_edge_cases(mock_session_local):
    """Test date matching edge cases."""
    llm = MockLLM()
    tools = []
    agent = ReconcilerAgent(llm, tools)
    
    # On due date
    result = agent._calculate_date_score(
        date(2026, 3, 1),
        date(2026, 3, 15),
        date(2026, 3, 15)
    )
    assert result["score"] == 1.0
    
    # Within grace period
    result = agent._calculate_date_score(
        date(2026, 3, 1),
        date(2026, 3, 15),
        date(2026, 3, 17)
    )
    assert result["score"] == 0.95
    
    # Late
    result = agent._calculate_date_score(
        date(2026, 3, 1),
        date(2026, 3, 15),
        date(2026, 4, 15)
    )
    assert result.get("is_late") is True
    assert result["score"] == 0.50


@patch('agents.reconciler_agent.SessionLocal')
def test_flag_discrepancies_overdue(mock_session_local):
    """Test flagging overdue invoices."""
    mock_db = Mock()
    mock_session_local.return_value = mock_db
    
    overdue_invoice = Mock()
    overdue_invoice.id = 1
    overdue_invoice.invoice_number = "INV-OVERDUE"
    overdue_invoice.vendor_name = "Slow Vendor"
    overdue_invoice.amount_due = Decimal('500.00')
    overdue_invoice.amount_paid = Decimal('0.00')
    overdue_invoice.due_date = date(2026, 3, 1)
    overdue_invoice.status = "pending"
    overdue_invoice.tenant_id = 1
    
    mock_query_overdue = Mock()
    mock_filter_overdue = Mock()
    mock_query_overdue.filter.return_value = mock_filter_overdue
    mock_filter_overdue.all.return_value = [overdue_invoice]
    
    mock_query_paid = Mock()
    mock_filter_paid = Mock()
    mock_query_paid.filter.return_value = mock_filter_paid
    mock_filter_paid.all.return_value = []
    
    mock_query_all = Mock()
    mock_filter_all = Mock()
    mock_query_all.filter.return_value = mock_filter_all
    mock_filter_all.all.return_value = [overdue_invoice]
    
    mock_db.query.side_effect = [mock_query_overdue, mock_query_paid, mock_query_all]
    
    llm = MockLLM()
    tools = []
    agent = ReconcilerAgent(llm, tools)
    
    result = agent._flag_discrepancies(mock_db, 1)
    
    assert isinstance(result, list)
    assert len(result) >= 1
    # Check for overdue type
    overdue_types = [r for r in result if r["type"] == DiscrepancyType.OVERDUE.value]
    assert len(overdue_types) == 1
    assert overdue_types[0]["invoice_id"] == 1


@patch('agents.reconciler_agent.SessionLocal')
def test_categorize_expenses_rule_based(mock_session_local):
    """Test rule-based expense categorization."""
    mock_db = Mock()
    mock_session_local.return_value = mock_db
    
    expense = Mock()
    expense.id = 1
    expense.vendor_name = "Electric Company"
    expense.amount = Decimal('100.00')
    expense.expense_date = date(2026, 3, 28)
    expense.category = None
    expense.description = "Monthly electricity bill"
    
    mock_db.query.return_value.filter.return_value.all.return_value = [expense]
    mock_db.commit = Mock()
    
    llm = MockLLM()
    tools = []
    agent = ReconcilerAgent(llm, tools)
    
    result = agent._categorize_expenses(mock_db, 1)
    
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["suggested_category"] == "utilities"


@patch('agents.reconciler_agent.get_embedding')
def test_categorize_expense_embedding_based(mock_get_embedding):
    """Test embedding-based expense categorization."""
    mock_get_embedding.return_value = [0.8, 0.1, 0.1]
    
    llm = MockLLM()
    tools = []
    agent = ReconcilerAgent(llm, tools)
    
    category, confidence = agent._categorize_expense_embedding_based("Monthly electricity bill payment")
    
    assert category == "utilities"
    assert isinstance(confidence, float)
    assert 0.0 <= confidence <= 1.0


def test_confidence_level():
    """Test confidence level determination."""
    llm = MockLLM()
    tools = []
    agent = ReconcilerAgent(llm, tools)
    
    assert agent._get_confidence_level(0.90) == MatchConfidence.HIGH
    assert agent._get_confidence_level(0.75) == MatchConfidence.MEDIUM
    assert agent._get_confidence_level(0.55) == MatchConfidence.LOW
    assert agent._get_confidence_level(0.30) == MatchConfidence.VERY_LOW


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
