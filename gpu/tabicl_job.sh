#!/bin/bash
#SBATCH --job-name=movenex-tabiclv2
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --time=01:00:00
#SBATCH --output=slurm-%j.log
set -euo pipefail
CODE_DIR="${ECT_CODE_DIR:-$HOME/Koreamovenex}"
WORK_DIR="${ECT_GPU_WORKDIR:-${SLURM_SUBMIT_DIR:-$PWD}}"
cd "$WORK_DIR"
test -f "$CODE_DIR/scripts/run_foundation_gpu.py"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1
export WANDB_MODE=disabled HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1 TOKENIZERS_PARALLELISM=false
.venv/bin/python -c "import torch; assert torch.cuda.is_available(); print(torch.__version__,torch.cuda.get_device_name())"
.venv/bin/python "$CODE_DIR/scripts/run_foundation_gpu.py" --work-dir "$WORK_DIR" "$@"
