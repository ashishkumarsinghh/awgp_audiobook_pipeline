Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "   AWGP Audiobook Production Pipeline Launcher        " -ForegroundColor Green
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "Starting WSL backend and frontend services..." -ForegroundColor Yellow
wsl -e bash -c "cd ~/projects/awgp_audiobook_pipeline && ./start.sh"
