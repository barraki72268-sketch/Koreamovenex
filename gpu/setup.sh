#!/bin/bash
set -euo pipefail
CODE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${1:?사용법: bash gpu/setup.sh /절대경로/gpu-work}"
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu128
.venv/bin/python -m pip install -r "$CODE_DIR/gpu/requirements.txt"
REV=c91f00df184a5097e584cb376f7e699e9f3444c4
if [ ! -e tabicl ]; then
  git clone https://github.com/soda-inria/tabicl.git tabicl
  git -C tabicl checkout --detach "$REV"
fi
test "$(git -C tabicl rev-parse HEAD)" = "$REV"
.venv/bin/python -m pip install -e "./tabicl[finetune]"
.venv/bin/python -m pip check
export HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_DISABLE_XET=1 DO_NOT_TRACK=1
.venv/bin/python -c "from huggingface_hub import hf_hub_download; from pathlib import Path; import hashlib; p=hf_hub_download(repo_id='jingang/TabICL',filename='tabicl-classifier-v2-20260212.ckpt',revision='4dcd344ece2c00be9e831fdd35bed57b5ad83e19',local_dir='checkpoints'); assert hashlib.sha256(Path(p).read_bytes()).hexdigest()=='bdc7dbd5e4ff21f8f0456fcf90c6b7cdf72dbea960f2d05b19bec19f9b3d4ed0'; print('체크포인트 해시 확인 완료')"
.venv/bin/python -m pip freeze > requirements.lock.txt
git -C tabicl rev-parse HEAD > source_commit.txt
