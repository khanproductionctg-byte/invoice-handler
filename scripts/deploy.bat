@echo off
REM ============================================================
REM CLI Deploy Script - Deploy from your local machine
REM Usage: deploy.bat YOUR_VM_IP
REM Requires: SSH key configured
REM ============================================================

set VM_IP=%1
set VM_USER=ubuntu
set APP_DIR=/opt/invoice-handler

if "%VM_IP%"=="" (
    echo Usage: deploy.bat YOUR_VM_IP
    echo Example: deploy.bat 123.456.789.012
    exit /b 1
)

echo ==========================================
echo Deploying to %VM_IP%...
echo ==========================================

echo [1/4] Uploading files...
scp -r . %VM_USER%@%VM_IP%:%APP_DIR%/

echo [2/4] Connecting to VM and deploying...
ssh %VM_USER%@%VM_IP% "cd %APP_DIR% && docker compose -f docker-compose.prod.yml down && docker compose -f docker-compose.prod.yml build --no-cache && docker compose -f docker-compose.prod.yml up -d"

echo [3/4] Waiting for services to start...
timeout /t 15 /nobreak

echo [4/4] Checking status...
ssh %VM_USER%@%VM_IP% "cd %APP_DIR% && docker compose -f docker-compose.prod.yml ps"

echo.
echo ==========================================
echo Deployment complete!
echo Backend: http://%VM_IP%:8000
echo API Docs: http://%VM_IP%:8000/docs
echo ==========================================
