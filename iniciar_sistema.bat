@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Iniciando Sistema Extractor de Letras y Coordenadas...
python app.py
pause

