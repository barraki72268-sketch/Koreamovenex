# 선택 실행: TabICLv2

새 크랙·샤프트 자료의 GPU 실행과 가중치 추가 학습은 [새 검사자료·GPU 가이드](새검사자료_GPU_가이드.md)를 참고하세요. 이 문서는 기존 03번의 CPU 비교 방법입니다.

기본 분석에 꼭 필요한 모델이 아닙니다. 먼저 01번 노트북의 거리 기준·Random Forest·XGBoost가 정상 작동하는지 확인하세요. 추가 비교가 필요한 담당자만 설치합니다.

## 어떤 모델인가요?

여러 표 데이터로 사전에 학습한 모델에 ‘입력값과 라벨이 있는 기준 샘플’과 ‘분석할 새 샘플’을 넣어 비교합니다. 이번 코드에서는 위치별 NG 마스터를 한쪽으로, 학습 OK와 기업 가성을 반대쪽으로 사용합니다. 기업 진성 및 같은 사건그룹은 학습에서 제외합니다.

![TabICLv2 사용 개념도](images/05_TabICLv2_구조.png)

공식 프로젝트: [soda-inria/tabicl](https://github.com/soda-inria/tabicl). 사용 버전은 commit `c91f00df184a5097e584cb376f7e699e9f3444c4`, 체크포인트는 `tabicl-classifier-v2-20260212.ckpt`입니다. 공식 저장소의 라이선스·모델 이용조건을 함께 확인하세요. 원본 모델 코드를 이 저장소에 복제하지 않았습니다.

## 설치

기본 설치가 끝난 프로젝트 폴더에서 실행합니다. 별도 Python 패키지와 모델 파일 다운로드가 필요합니다. Git도 설치되어 있어야 합니다. CPU용 PyTorch가 이미 준비되어 있다면 해당 환경을 활용할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-optional-tabicl.txt
.\.venv\Scripts\python.exe -m pip check
```

기본 코드가 사용하는 `n_estimators=4`, CPU, seed 42 설정을 유지합니다. GPU 설정 변경은 이 설치 가이드의 범위 밖입니다.

## 모델 파일 받기

프로젝트 폴더에서 아래를 실행하면 공식 Hugging Face 모델 저장소에서 체크포인트를 받습니다. 이 단계는 공개 모델만 다운로드합니다.

```powershell
.\.venv\Scripts\python.exe -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='jingang/TabICL', filename='tabicl-classifier-v2-20260212.ckpt', local_dir='checkpoints')"
```

모델 파일은 약 110MB이며 Git에 올리지 않습니다. 기관에서 별도로 준비한 파일이 있으면 같은 이름으로 `checkpoints`에 넣어도 됩니다.

## 실행과 저장

1. `start_notebook.cmd`로 Jupyter를 엽니다.
2. `notebooks/03_선택_TabICLv2_비교.ipynb`를 엽니다.
3. 기본 `DATA_MODE = "demo"`로 먼저 확인합니다.
4. 실제 회사 파일이 있으면 `DATA_MODE = "company"`로 바꿉니다.
5. 위에서 아래로 실행합니다.
6. 결과는 기본 모델과 마찬가지로 `results/실행시각`에 저장됩니다.

모델 점수는 실제 불량 확률이 아닙니다. 마스터가 양산 진성 전체를 대표한다고 가정할 수 없으며, 현재 진성 표본 부족과 날짜 검증 한계도 그대로 적용됩니다. 추가 모델의 결과가 좋아 보여도 새 날짜의 진성·가성으로 확인해야 합니다.
