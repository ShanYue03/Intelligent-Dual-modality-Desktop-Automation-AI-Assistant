# Install CUDA-enabled PyTorch first, then project deps (fast HF router on NVIDIA GPU).
#
# PyTorch index note: cu124 wheels start at torch 2.4.x. For torch<2.4 (matches
# requirements.txt / NumPy pin), use cu118 or cu121 (default).
#
# Usage (from this folder, in your conda/venv):
#   .\install_router_gpu.ps1
#   .\install_router_gpu.ps1 -Cuda cu118
#   .\install_router_gpu.ps1 -Cuda cu124   # installs torch 2.4+ (newer stack)
#
param(
    [ValidateSet("cu118", "cu121", "cu124")]
    [string]$Cuda = "cu118"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

$Index = "https://download.pytorch.org/whl/$Cuda"
if ($Cuda -eq "cu124") {
    $TorchSpec = "torch>=2.4.0,<2.7.0"
    Write-Host "==> cu124: installing $TorchSpec (2.3.x not published on this index)"
} else {
    $TorchSpec = "torch>=1.13.0,<2.4.0"
}

Write-Host "==> Installing torch ($TorchSpec, CUDA $Cuda) from $Index"
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
python -m pip uninstall -y torch 2>&1 | Out-Null
$ErrorActionPreference = $prevEap
python -m pip install $TorchSpec --index-url $Index

Write-Host "==> Installing remaining requirements (torch is not in requirements.txt)"
python -m pip install -r "$Root\requirements.txt"

Write-Host "==> Verify (expect cuda_available True)"
python -c "import torch; ok=torch.cuda.is_available(); print('torch', torch.__version__); print('cuda_available', ok); import sys; sys.exit(0 if ok else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "CUDA not usable with this PyTorch build. Update NVIDIA drivers, then re-run this script."
    Write-Host "If your driver is already new (CUDA 12.x), try: .\install_router_gpu.ps1 -Cuda cu121"
    Write-Host "See https://pytorch.org/get-started/locally/"
    exit 1
}
