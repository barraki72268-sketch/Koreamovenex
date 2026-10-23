FROM python:3.12-slim-bookworm AS notebooks
WORKDIR /clean
COPY notebooks/ ./
RUN python -c "import json,pathlib; files=list(pathlib.Path('.').glob('*.ipynb')); [(p.write_text(json.dumps({**(n:=json.loads(p.read_text())), 'cells':[{**c, **({'outputs':[], 'execution_count':None} if c['cell_type']=='code' else {})} for c in n['cells']]},ensure_ascii=False,indent=1),encoding='utf-8')) for p in files]"

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=module://matplotlib_inline.backend_inline OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
    HOME=/tmp/ect-home JUPYTER_RUNTIME_DIR=/tmp/jupyter-runtime ECT_PROJECT_ROOT=/workspace
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 fonts-noto-cjk && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1000 ect && useradd -m -u 1000 -g 1000 ect
WORKDIR /workspace
COPY requirements.txt /opt/ect/requirements.txt
RUN python -m pip install --no-cache-dir -r /opt/ect/requirements.txt \
    && python -m pip check \
    && HOME=/root python -m ipykernel install --sys-prefix --name movenex-ect --display-name "Python (Movenex ECT)"
COPY ectlab/ ./ectlab/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY data/demo/ ./data/demo/
COPY docker/ /opt/ect/docker/
COPY --from=notebooks /clean/ /opt/ect/notebooks/
RUN mkdir -p /workspace/data/private /workspace/data/raw /output \
    && ln -s /output/notebooks /workspace/notebooks \
    && ln -s /output/results /workspace/results \
    && ln -s /output/processed /workspace/data/processed \
    && chown -R ect:ect /output
USER 1000:1000
EXPOSE 8888
ENTRYPOINT ["python", "/opt/ect/docker/start.py"]
