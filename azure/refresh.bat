@echo off
REM ============================================================================
REM Reload the master spreadsheet into Azure SQL. The database becomes an exact
REM mirror of the file (full reload via --if-exists replace), so adding rows to
REM the file each week/month and running this keeps the DB up to date with no
REM duplicate risk.
REM
REM Use it two ways:
REM   * Double-click after you add rows (manual one-click refresh), or
REM   * Point Windows Task Scheduler at it for a weekly/monthly auto-refresh.
REM
REM Requires: refresh.config (copy from refresh.config.example) and the
REM SQLPASSWORD environment variable set. See README "Scheduling".
REM ============================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist "refresh.config" (
    echo [ERROR] refresh.config not found. Copy refresh.config.example to refresh.config and edit it.
    pause
    exit /b 1
)

REM Load KEY=VALUE lines from refresh.config (skipping comments).
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("refresh.config") do (
    set "%%A=%%B"
)

if "%SQLPASSWORD%"=="" (
    echo [ERROR] SQLPASSWORD environment variable is not set.
    echo         See README "Scheduling" for how to set it as a persistent user variable.
    pause
    exit /b 1
)

echo Reloading "%DATA_FILE%" into %DATABASE%.%TABLE% ...
python "%~dp0load_data.py" "%DATA_FILE%" ^
    --table "%TABLE%" ^
    --server "%SERVER%" ^
    --database "%DATABASE%" ^
    --user "%DB_USER%" ^
    --if-exists replace

if errorlevel 1 (
    echo [ERROR] Load failed. See messages above.
    pause
    exit /b 1
)

echo Done. Refresh your Power BI report to see the latest data.
