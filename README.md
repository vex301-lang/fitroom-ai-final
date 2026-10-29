# 한신초 AI 교복 사진 부스 (FASHN API 버전)

학생 사진을 촬영하거나 업로드하면 **FASHN API**를 사용해 더 자연스러운 교복 사진을 생성하는 웹 앱입니다.

## 핵심 방식

기존의 “얼굴만 붙이는” 합성이 아니라 다음 2단계로 처리합니다.

1. **Model Swap**
   - 기준 교복 이미지(남학생/여학생)를 `model_image`로 사용
   - 학생 촬영 사진을 `face_reference`로 사용
   - 얼굴, 머리카락, 피부 톤을 학생에 맞게 바꿉니다.
2. **Edit (선택)**
   - Model Swap 결과를 학교 배경에 자연스럽게 놓고
   - 얼굴/목선/머리카락 경계, 조명, 원근을 더 자연스럽게 보정합니다.

## 포함 파일

- `app.py` : FastAPI 서버
- `static/` : 웹 UI
- `assets/boy_uniform.png` : 남학생 교복 기준 이미지
- `assets/girl_uniform.png` : 여학생 교복 기준 이미지
- `assets/hansin_background.png` : 한신초 배경 이미지
- `render.yaml` : Render 배포용 설정
- `.env.example` : 환경 변수 예시

## 로컬 실행

```bash
pip install -r requirements.txt
cp .env.example .env
# .env에 FASHN_API_KEY 입력
uvicorn app:app --reload
```

브라우저에서:

```text
http://127.0.0.1:8000
```

## Render 배포

1. 이 폴더 전체를 GitHub 저장소에 업로드합니다.
2. Render에서 **New + > Web Service**를 선택합니다.
3. GitHub 저장소를 연결합니다.
4. 환경 변수에 다음을 입력합니다.
   - `FASHN_API_KEY` = 발급받은 키
   - `FASHN_API_BASE` = `https://api.fashn.ai/v1`
   - `DEFAULT_RESOLUTION` = `2k`
   - `DEFAULT_GENERATION_MODE` = `balanced`
5. Build Command: `pip install -r requirements.txt`
6. Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT`

## 권장 사용법

- 카메라 또는 업로드 사진은 **정면에 가깝고 얼굴과 머리카락이 잘 보이게** 촬영합니다.
- 기본적으로 **고품질 배경/자연스러움 보정**을 켜 두는 것을 권장합니다.
- 빠르게 테스트할 때는 체크를 끄면 1단계(Model Swap)만 수행합니다.

## 크레딧 참고

문서 기준으로 `model-swap`은 해상도와 품질에 따라 비용이 달라지고, `face_reference`를 쓰면 추가 비용이 붙습니다. `edit`는 별도 비용이 더 듭니다. 실제 과금은 FASHN 대시보드와 최신 문서를 확인해 주세요.

## 개인정보 유의

- 이 앱은 FASHN API에 학생 사진을 전송합니다.
- 학생 사진이므로 **보호자 동의와 안내 문구**를 운영 전에 준비하는 것을 권장합니다.
- 앱 서버에는 생성 결과 파일만 일시 저장되며, `results` 폴더는 주기적으로 정리됩니다.

## 참고

이 프로젝트는 FASHN의 범용 `/v1/run` 및 `/v1/status/{id}` 패턴을 사용하도록 작성되었습니다. 최신 파라미터가 바뀌면 FASHN 공식 문서에 맞게 조정해 주세요.
