@echo off
echo ======================================================
echo    AWGP Audiobook Production Pipeline Launcher
echo ======================================================
echo Starting WSL backend and frontend services...
wsl -e bash -c "cd ~/projects/awgp_audiobook_pipeline && ./start.sh"
pause
