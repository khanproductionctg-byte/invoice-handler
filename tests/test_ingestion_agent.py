"""
Test for the IngestionAgent.
"""
import pytest
import logging
from unittest.mock import Mock, patch, MagicMock
import json
from datetime import date, timedelta

logger = logging.getLogger(__name__)

from agents.ingestion_agent import IngestionAgent

# Mock data for ingestion tools
MOCK_GMAIL_RESULT = json.dumps([
    {
        "invoice_number": "GMAIL123",
        "vendor_name": "Test Vendor",
        "amount_due": 100.00,
        "invoice_date": "2026-03-28",
        "due_date": "2026-04-27",
        "source": "gmail",
        "source_id": "msg123",
        "user_id": 1
    }
])

MOCK_DRIVE_RESULT = json.dumps([
    {
        "invoice_number": "DRIVE123",
        "vendor_name": "Test Vendor 2",
        "amount_due": 200.00,
        "invoice_date": "2026-03-28",
        "due_date": "2026-04-27",
        "source": "drive",
        "source_id": "file123",
        "user_id": 1
    }
])

MOCK_QB_RESULT = json.dumps([
    {
        "invoice_number": "QB123",
        "vendor_name": "Test Vendor 3",
        "amount_due": 300.00,
        "invoice_date": "2026-03-28",
        "due_date": "2026-04-27",
        "source": "quickbooks",
        "source_id": "QB123",
        "user_id": 1
    }
])

MOCK_XERO_RESULT = json.dumps([
    {
        "invoice_number": "XERO123",
        "vendor_name": "Test Vendor 4",
        "amount_due": 400.00,
        "invoice_date": "2026-03-28",
        "due_date": "2026-04-27",
        "source": "xero",
        "source_id": "xero123",
        "user_id": 1
    }
])

MOCK_PLAID_RESULT = json.dumps({
    "transactions": [
        {
            "vendor_name": "Test Vendor 5",
            "amount": 50.00,
            "date": "2026-03-28",
            "category": "Food and Drink",
            "description": "Test transaction",
            "source": "plaid",
            "source_id": "txn123",
            "user_id": 1,
            "account_id": "acc123"
        }
    ],
    "statements": [],
    "fetch_date": "2026-03-28T10:00:00Z"
})

def test_ingestion_agent_initialization():
    """Test that the IngestionAgent initializes correctly."""
    # We don't need to pass any tools to the IngestionAgent constructor in our current implementation
    # because the tools are fetched inside the agent. However, the constructor expects a list of tools.
    # We'll pass an empty list for now.
    agent = IngestionAgent([])
    assert agent.agent_name == "IngestionAgent"
    # In our implementation, we store tools in a dictionary format for easy lookup
    # but we ignore the passed tools and use our own hardcoded ones
    assert isinstance(agent.tools, dict)

@patch('agents.ingestion_agent.fetch_gmail_invoices')
@patch('agents.ingestion_agent.fetch_drive_pdfs')
@patch('agents.ingestion_agent.fetch_quickbooks_invoices')
@patch('agents.ingestion_agent.fetch_xero_invoices')
@patch('agents.ingestion_agent.fetch_plaid_transactions_and_statements')
def test_ingestion_agent_process_success(mock_plaid, mock_xero, mock_qb, mock_drive, mock_gmail):
    """Test successful processing of ingestion agent."""
    # Set up the mocks to return our synthetic data
    mock_gmail.invoke.return_value = MOCK_GMAIL_RESULT
    mock_drive.invoke.return_value = MOCK_DRIVE_RESULT
    mock_qb.invoke.return_value = MOCK_QB_RESULT
    mock_xero.invoke.return_value = MOCK_XERO_RESULT
    mock_plaid.invoke.return_value = MOCK_PLAID_RESULT

    # Create the agent
    agent = IngestionAgent([])  # We pass an empty list but the agent will ignore it and use its own tools

    # Create a test state
    from agents.base_agent import AgentState
    state = AgentState(
        input_data={
            "user_id": 1,
        }
    )

    # Run the agent
    result_state = agent.process(state)

    # Assertions
    assert result_state.output_data["status"] == "ingestion_completed"
    assert "ingestion_results" in result_state.output_data
    results = result_state.output_data["ingestion_results"]

    # Check that all sources were called
    assert "gmail" in results
    assert "drive" in results
    assert "quickbooks" in results
    assert "xero" in results
    assert "plaid" in results

    # Check that the data is correct
    gmail_data = json.loads(results["gmail"])
    assert len(gmail_data) == 1
    assert gmail_data[0]["invoice_number"] == "GMAIL123"
    assert gmail_data[0]["vendor_name"] == "Test Vendor"
    assert gmail_data[0]["amount_due"] == 100.00

    drive_data = json.loads(results["drive"])
    assert len(drive_data) == 1
    assert drive_data[0]["invoice_number"] == "DRIVE123"
    assert drive_data[0]["vendor_name"] == "Test Vendor 2"
    assert drive_data[0]["amount_due"] == 200.00

    qb_data = json.loads(results["quickbooks"])
    assert len(qb_data) == 1
    assert qb_data[0]["invoice_number"] == "QB123"
    assert qb_data[0]["vendor_name"] == "Test Vendor 3"
    assert qb_data[0]["amount_due"] == 300.00

    xero_data = json.loads(results["xero"])
    assert len(xero_data) == 1
    assert xero_data[0]["invoice_number"] == "XERO123"
    assert xero_data[0]["vendor_name"] == "Test Vendor 4"
    assert xero_data[0]["amount_due"] == 400.00

    plaid_data = json.loads(results["plaid"])
    assert "transactions" in plaid_data
    assert len(plaid_data["transactions"]) == 1
    assert plaid_data["transactions"][0]["vendor_name"] == "Test Vendor 5"
    assert plaid_data["transactions"][0]["amount"] == 50.00

def test_ingestion_agent_process_failure():
    """Test that the agent handles failures gracefully."""
    # We'll make one of the tools fail
    with patch('agents.ingestion_agent.fetch_gmail_invoices') as mock_gmail, \
         patch('agents.ingestion_agent.fetch_drive_pdfs') as mock_drive, \
         patch('agents.ingestion_agent.fetch_quickbooks_invoices') as mock_qb, \
         patch('agents.ingestion_agent.fetch_xero_invoices') as mock_xero, \
         patch('agents.ingestion_agent.fetch_plaid_transactions_and_statements') as mock_plaid:

        # Mock the invoke method to raise an exception for gmail
        mock_gmail.invoke.side_effect = Exception("Gmail API error")
        mock_drive.invoke.return_value = MOCK_DRIVE_RESULT
        mock_qb.invoke.return_value = MOCK_QB_RESULT
        mock_xero.invoke.return_value = MOCK_XERO_RESULT
        mock_plaid.invoke.return_value = MOCK_PLAID_RESULT

        agent = IngestionAgent([])
        from agents.base_agent import AgentState
        state = AgentState(input_data={"user_id": 1})

        result_state = agent.process(state)

        # The agent should still complete but with an error in the gmail result
        assert result_state.output_data["status"] == "ingestion_completed"
        results = result_state.output_data["ingestion_results"]
        assert "Error:" in results["gmail"]
        # The other sources should still have succeeded
        assert json.loads(results["drive"])[0]["invoice_number"] == "DRIVE123"

if __name__ == "__main__":
    pytest.main([__file__])