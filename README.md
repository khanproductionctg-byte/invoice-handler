# Invoice Handler - AI-Powered Invoice & Expense Reconciliation + Payment Chasing Agent

A comprehensive AI-powered system for automating invoice processing, expense reconciliation, and payment chasing.

## Features

- **Multi-source Data Integration**: Pull invoices/expenses from Gmail, Google Drive, QuickBooks Online, Xero, and Plaid
- **Intelligent PDF Parsing**: Extract structured data from PDF invoices and receipts
- **AI-Powered Matching**: Automatically match payments to invoices using LLMs and embeddings
- **Smart Discrepancy Detection**: Flag amount mismatches, duplicates, and late payments
- **Automated Payment Chasing**: Send personalized email/SMS reminders with escalation
- **Financial Reporting**: Generate weekly/monthly reports and alerts
- **Multi-agent Architecture**: Built with LangGraph for sophisticated workflow orchestration

## Tech Stack

- **Backend**: FastAPI
- **Orchestration**: LangGraph
- **Database**: PostgreSQL + pgvector (for embeddings)
- **Task Queue**: Celery + Redis
- **LLM**: Local LLM endpoint (Ollama compatible) or API
- **Embeddings**: sentence-transformers/all-MiniLM-L6-v2
- **Integrations**: 
  - Plaid (bank transactions)
  - Xero & QuickBooks (accounting)
  - Google API (Gmail, Drive)
  - Twilio (SMS)
  - SendGrid (Email)
- **Document Processing**: pdfplumber
- **Data Validation**: Pydantic
- **Testing**: Pytest

## Project Structure

```
invoice_handler/
├── api/                  # FastAPI application
│   ├── main.py          # API entry point
│   └── routes/          # API route modules
├── agents/              # LangGraph agents
│   ├── base_agent.py    # Base agent class
│   ├── orchestrator.py  # Workflow orchestrator
│   ├── reconciler_agent.py
│   ├── chaser_agent.py
│   └── reporter_agent.py
├── core/                # Core business logic
├── db/                  # Database models and setup
│   ├── models.py        # SQLAlchemy models
│   └── database.py      # Database connection
├── models/              # Pydantic models (if separate from schemas)
├── schemas/             # Pydantic schemas for validation
│   ├── user.py
│   ├── invoice.py
│   ├── expense.py
│   ├── payment.py
│   └── report.py
├── utils/               # Utility functions
│   ├── pdf_parser.py    # PDF text extraction
│   ├── embedding.py     # Text vectorization
│   ├── email_sender.py  # SendGrid integration
│   ├── sms_sender.py    # Twilio integration
│   ├── template_renderer.py
│   ├── report_generator.py
│   └── alert_system.py
├── worker/              # Celery workers
│   ├── celery_worker.py # Celery app configuration
│   └── tasks/           # Celery tasks
├── templates/           # Jinja2 templates for emails/SMS
├── tests/               # Unit and integration tests
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variables template
├── docker-compose.yml   # Docker Compose configuration
└── README.md            # This file
```

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd invoice_handler
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set up environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. Set up the database:
   ```bash
   # Using Docker Compose (recommended)
   docker-compose up -d
   
   # Or manually create PostgreSQL database and update .env
   ```

6. Run database migrations:
   ```bash
   # Alembic migrations would go here
   # For now, tables are created automatically on startup
   ```

## Running the Application

### Development Mode

```bash
# Start the API server
uvicorn api.main:app --reload

# Start the Celery worker (in another terminal)
celery -A worker.celery_worker.celery_app worker --loglevel=info
```

### Using Docker Compose

```bash
docker-compose up --build
```

The API will be available at `http://localhost:8000`

## API Endpoints

- `GET /` - Root endpoint
- `POST /token` - Get authentication token
- `POST /users/` - Register a new user
- `GET /users/me/` - Get current user info
- `GET /health` - Health check

*(Additional endpoints for invoices, expenses, payments, and reports would be implemented in the route modules)*

## Configuration

Copy `.env.example` to `.env` and configure:

### Required Settings
- `SECRET_KEY` - For JWT token signing
- Database connection parameters (`POSTGRES_*`)
- Redis connection parameters (`REDIS_*`)
- LLM configuration (`LLM_BASE_URL`, `LLM_MODEL`)
- API keys for integrations:
  - Google (Gmail, Drive)
  - Plaid
  - Xero
  - QuickBooks
  - Twilio
  - SendGrid

### Optional Settings
- `ALERT_THRESHOLD_OVERDUE` - Overdue amount threshold for alerts (default: 1000)
- `REPORT_GENERATION_TIME` - Cron expression for automated reports
- `CORS_ORIGINS` - Allowed CORS origins

## Testing

Run the test suite:

```bash
pytest
```

## Security Notes

1. **Environment Variables**: Never commit `.env` file to version control. Use `.env.example` as a template.
2. **API Keys**: All service credentials should be stored in environment variables.
3. **Database Connections**: Use connection pooling and proper credentials management.
4. **Input Validation**: All API inputs are validated using Pydantic schemas.
5. **PDF Processing**: PDF files are processed in-memory where possible to reduce attack surface.
6. **Rate Limiting**: Consider implementing rate limiting for external API calls in production.
7. **Error Handling**: Errors are logged but sensitive information is not exposed in API responses.
8. **Secure Communications**: Use HTTPS in production environments.

## Future Enhancements

- [ ] User interface (React/Vue frontend)
- [ ] Advanced ML models for expense categorization
- [ ] Customizable workflow rules engine
- [ ] Multi-currency support with automatic conversion
- [ ] Advanced analytics and forecasting
- [ ] Audit trail and compliance reporting
- [ ] Role-based access control (RBAC)
- [ ] Webhook support for real-time updates from external systems

## License

[To be specified]

## Support

[To be specified]