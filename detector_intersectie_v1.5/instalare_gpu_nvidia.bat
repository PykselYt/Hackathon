@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo Instalez PyTorch cu suport pentru placa video NVIDIA...
pip uninstall -y torch torchvision
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
python -c "import torch; print('Placa NVIDIA disponibila:', torch.cuda.is_available())"
pause
