@echo off
rem 캡컷 자동 편집 작업 화면 열기
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -3.11 pipeline\app.py) || (py -3.11 pipeline\app.py)
