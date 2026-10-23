# Docker로 서버·NAS에서 실행하기

서버 담당자가 Docker를 준비하고 CSV 폴더를 연결하면, 사용자는 브라우저에서 노트북을 열어 실행할 수 있습니다. 기본 분석은 CPU로 동작하며 GPU나 PyTorch 설치가 필요하지 않습니다. 이 구성은 한 회사·한 작업 공간 기준입니다. 서로 다른 사용자의 계정과 파일을 분리하려면 JupyterHub 등 별도의 운영 구성이 필요합니다.

처음 설치하는 순서는 [README의 Docker 실행](../README.md#docker로-실행)을 따릅니다.

## 어떤 파일을 전달하나

| 자료 | 전달 방법 |
|---|---|
| 분석 코드와 Docker 설정 | GitHub 저장소 링크 |
| 회사 CSV | 회사가 승인한 파일 전달 경로로 서버 담당자에게 별도 전달 |
| .env | 담당자가 실제 서버 경로에 맞게 작성. Git에 올리지 않음 |
| 실행 노트북 주소 | 서버 설치·접속 확인 후 기업 담당자에게 전달 |

Docker 이미지는 프로그램을 담는 실행 환경입니다. 회사 CSV를 이미지에 넣거나 공개 저장소로 업로드할 필요는 없습니다. 이 저장소는 합성 데이터만 이미지에 복사하고, 실제 CSV는 실행할 때 서버 폴더로 연결합니다. 빌드 과정에서 노트북의 실행 출력과 실행 번호도 지웁니다.

현재는 서버에서 `docker compose up --build`로 이미지를 만드는 방식입니다. Docker Hub나 GHCR에 미리 배포된 이미지를 받는 구성은 아닙니다.

## 서버와 NAS 연결

Docker를 NAS 자체에서 실행하면 `/volume1/...` 등 NAS 내부 경로를 사용합니다. Docker가 다른 Linux 서버에서 돌아가면 먼저 NAS 공유 폴더를 SMB/NFS 등으로 연결하고, 서버에서 실제로 보이는 경로를 사용합니다.

예를 들어 NAS 공유가 Linux 서버의 `/mnt/movenex`에 연결돼 있다면 `.env`는 다음과 같습니다.

```dotenv
ECT_CSV_DIR=/mnt/movenex/csv
ECT_OUTPUT_DIR=/mnt/movenex/output
```

사용할 `csv`, `output` 폴더가 실제로 존재해야 합니다. 없는 경로를 자동으로 만들지 않도록 구성했습니다. CSV는 읽기 전용이고, 결과와 노트북은 출력 폴더에 저장합니다. 이 연결 방식은 [Docker bind mount](https://docs.docker.com/engine/storage/bind-mounts/)를 사용합니다.

Linux·NAS는 `ECT_UID`, `ECT_GID`와 공유 폴더의 권한을 맞춥니다. 폴더 계정 번호가 다른데 기본값 1000으로 실행하면 저장 권한 오류가 발생할 수 있습니다. NAS의 ACL도 확인합니다. 32비트 ARM NAS는 이 배포본의 지원 대상이 아니며, 자동 검증은 Linux x86-64에서 수행합니다. ARM64 NAS는 패키지 설치 및 실행을 해당 장비에서 별도로 확인해야 합니다.

## 다른 PC에서 접속

기본 설정은 서버 내부에서만 접속하도록 `127.0.0.1`에 연결합니다. 다음 중 서버 환경에 맞는 방법을 사용합니다.

### SSH로 서버에 접속하는 경우

사용자 PC의 터미널에서 실행하고 창을 열어 둡니다.

```bash
ssh -L 8888:127.0.0.1:8888 계정@서버주소
```

사용자 PC의 브라우저에서 `http://127.0.0.1:8888`로 접속합니다. 토큰은 서버에서 다음 명령으로 확인합니다.

```bash
docker compose exec notebook python -m jupyter server list
```

### 내부망에서 바로 접속하는 경우

`.env`에서 `ECT_BIND_IP`를 Docker 서버가 실제로 사용하는 내부 IP로 설정합니다.

```dotenv
ECT_BIND_IP=192.168.0.50
ECT_PORT=8888
```

다음 명령으로 새 설정을 적용하고, 브라우저에서 `http://192.168.0.50:8888`로 접속합니다. `192.168.0.50`은 예시이므로 실제 주소로 바꿉니다. 서버 방화벽과 NAS 방화벽에서 해당 내부망 접속을 허용해야 합니다.

```bash
docker compose up -d --wait --wait-timeout 180
```

인터넷을 통한 접속은 기관의 HTTPS 프록시나 VPN에 연결합니다. Jupyter의 토큰 인증은 유지합니다. 토큰이 포함된 링크를 공개 README나 공지에 게시하지 않습니다. 참고: [Jupyter 인증 안내](https://jupyter-server.readthedocs.io/en/latest/operators/security.html).

로그인 뒤 기본 노트북을 열어 브라우저 주소를 복사하면 전달할 노트북 링크를 얻을 수 있습니다. URL이 `localhost` 또는 `127.0.0.1`이면 해당 컴퓨터에서만 유효합니다. 상대방이 접속할 수 있는 서버 주소를 사용합니다.

## 추가 CSV와 재학습

### 전체 데이터가 갱신된 경우

1. 새 전체 CSV를 `ECT_CSV_DIR`에 넣습니다. 실행 중인 파일을 덮어쓰기보다는 새 파일명을 사용합니다.
2. `.env`의 `ECT_CSV_FILE`을 새 파일명으로 바꿉니다. 품번이 바뀌면 `ECT_PRODUCT`도 변경합니다.
3. `docker compose up -d --wait --wait-timeout 180`으로 설정을 적용합니다.
4. 01번 노트북에서 커널을 재시작하고 전체 실행합니다. 선택한 파일명이 새 파일인지 확인합니다.

01번 노트북은 매번 입력 CSV로 거리 기준과 RF·XGBoost를 다시 학습합니다. 추가 날짜를 학습에 사용하려면 학습·기준 설정 날짜도 바꿔야 합니다. 새 CSV를 넣었다고 날짜 구간이 자동으로 바뀌지는 않습니다. 위치 1·2는 계속 따로 처리합니다.

### 새 날짜 추가분을 기존 CSV와 합치는 경우

기존 파일과 추가분을 모두 CSV 폴더에 넣습니다. 02번 노트북의 준비 셀과 ①을 실행한 뒤, `NEW_CSV`를 추가분 파일로 지정합니다.

```python
NEW_CSV = ROOT / "data/private/추가분.csv.gz"
```

CSV를 이미 받았으므로 ② Excel 변환은 건너뜁니다. ③에서 `MERGE_FILES = True`로 바꾸고 병합한 뒤, ④에서 `TRAINING_CSV = MERGED_CSV`와 날짜를 정해 학습합니다. 병합·변환 결과는 서버의 `ECT_OUTPUT_DIR/processed`에 남습니다. 입력 폴더에 쓰지 않습니다.

전체 기간이 포함된 회신본을 기존 데이터에 다시 합치면 중복이 됩니다. 전체 갱신본은 교체하고, 날짜가 다른 추가분만 병합합니다. 상세 형식은 [추가 데이터 가이드](추가데이터_가이드.md)를 참고합니다.

Docker 기본 구성은 CSV 연결용입니다. 원본·회신 Excel을 Docker 안에서 변환하려면 해당 폴더를 `/workspace/data/raw`에 추가로 연결해야 합니다. 현재 설정에 Excel이 자동으로 연결되지는 않습니다.

## 결과 보관과 업데이트

서버의 `ECT_OUTPUT_DIR` 아래에 `results`, `processed`, `notebooks`가 만들어집니다. 노트북에서 `Ctrl + S`로 저장한 설정과 실행 출력도 이 위치에 남습니다. 컨테이너를 다시 만들어도 파일은 보존됩니다. 입력 CSV와 이 출력 폴더를 백업하면 됩니다.

노트북은 처음 실행할 때만 복사하며 이후에는 사용자가 저장한 설정을 유지합니다. 프로그램을 업데이트해도 기존 노트북을 자동으로 덮어쓰지 않습니다.

```bash
git pull
docker compose up -d --build --wait --wait-timeout 180
```

새 버전의 노트북이 필요하면 Jupyter에서 기존 노트북을 다른 이름으로 보관한 다음, 다음 명령으로 기본 노트북을 다시 복사합니다. 새 노트북은 서버 환경 설정을 읽습니다. 복사 전에 작업 중인 내용을 저장합니다.

```bash
docker compose exec notebook python -c "import shutil; shutil.copyfile('/opt/ect/notebooks/01_처음부터_분석하기.ipynb', '/workspace/notebooks/01_처음부터_분석하기.ipynb')"
```

컨테이너를 새로 만들면 로그인 토큰이 바뀔 수 있습니다. `jupyter server list`로 다시 확인합니다.

## 문제 해결

| 증상 | 확인 사항 |
|---|---|
| `docker` 명령을 찾지 못함 | Docker 설치와 실행 상태 |
| `compose` 또는 `--wait`를 인식하지 못함 | 현재 Docker Compose v2 설치·업데이트 |
| `.env` 관련 오류 | `.env.example`을 `.env`로 복사했는지, 두 폴더 경로를 지정했는지 |
| bind source path 오류 | Docker가 실행되는 서버에서 경로가 존재하는지 |
| 회사 CSV가 없다는 오류 | 폴더와 파일명을 나눠 적었는지, 대소문자와 확장자가 맞는지 |
| 출력 폴더 권한 오류 | UID·GID와 NAS 읽기·쓰기 권한 |
| 다른 PC에서 접속 불가 | 기본 주소는 서버 내부용. SSH 터널, 실제 서버 IP, 방화벽 확인 |
| 포트 사용 중 | `.env`의 `ECT_PORT`를 8889 등으로 변경하고 재시작 |
| 토큰 로그인 실패 | 컨테이너 재생성 후 토큰을 다시 확인 |
| 추가 날짜가 학습되지 않음 | CSV 선택과 학습 종료일·기준 설정 종료일 확인 |
| 업데이트 후 노트북이 그대로임 | 저장한 노트북을 보존하는 동작. 보관 후 새 기본 파일 복사 |

실행 상태는 `docker compose ps`로 확인합니다. 오류는 `docker compose logs --tail=80 notebook`으로 볼 수 있습니다. 로그에 로그인 토큰이 포함될 수 있으므로 공개 게시 전 제거합니다.

## 자동 검증 범위

[GitHub Actions](https://github.com/barraki72268-sketch/Koreamovenex/actions/workflows/docker-check.yml)에서 합성 CSV를 회사 CSV와 같은 경로로 연결해 다음 과정을 확인합니다.

- 이미지 빌드와 패키지 의존성 점검
- 위치 분리·학습 날짜·진성 학습 제외 등 분석 규칙
- 회사 CSV가 없으면 중단하고 합성 데이터로 대체하지 않는 동작
- 입력 CSV의 읽기 전용 연결
- 토큰 없는 접속 차단과 인증 후 노트북·결과 조회
- 01번 노트북의 모든 셀 실행과 한글 그래프·CSV·HTML·위치별 모델 저장
- 컨테이너를 교체한 뒤 노트북과 결과 유지

이는 배포 프로그램의 실행 검증입니다. 실제 NAS의 공유 권한, 네트워크 주소와 회사 데이터의 예측 성능은 별도 확인 항목입니다.
