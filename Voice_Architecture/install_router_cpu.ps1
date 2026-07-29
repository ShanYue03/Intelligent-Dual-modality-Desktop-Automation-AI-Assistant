# Install CPU-only PyTorch from PyPI, then project deps (slow router; use if no NVIDIA GPU).
# Usage (from this folder, in your conda/venv):
#   .\install_router_cpu.ps1

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

Write-Host "==> Installing torch (CPU) from PyPI"
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
python -m pip uninstall -y torch 2>&1 | Out-Null
$ErrorActionPreference = $prevEap
python -m pip install "torch>=1.13.0,<2.4.0"

Write-Host "==> Installing requirements"
python -m pip install -r "$Root\requirements.txt"

Write-Host "==> Verify"
python -c "import torch; print('torch', torch.__version__); print('cuda_available', torch.cuda.is_available())"
