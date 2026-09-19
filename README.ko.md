# sessionreel

**에이전트는 두 시간 일했고, 보여줄 건 35초면 됩니다.**

`sessionreel`은 Claude Code 세션 로그를 읽어 짧은 리캡 영상을 만듭니다. 요청이 무엇이었는지,
어떤 테스트가 빨간불이 됐는지, 어떤 diff가 그걸 고쳤는지, 다시 초록불이 된 실행, 그리고 배포까지.
모두 로컬에서 돌고, 그리기 전에 비밀값을 가리며, API 키가 필요 없습니다.

<p align="center"><img src="docs/demo.gif" width="600" alt="sessionreel 데모: 2 failed → 14 passed, 35초"></p>

```
uvx sessionreel            # 이 디렉터리의 최신 세션 → reel.mp4
uvx sessionreel --lang ko  # 한국어 자막
```

## 왜 만들었나

에이전트 세션은 분명한 작업인데 다른 사람은 볼 방법이 없습니다. 동료는 30 MB 트랜스크립트를
넘겨보지 않고, 고객은 리플레이 뷰어를 열지 않으며, X에 올린 링크는 영상이 아닙니다. 지금 있는
도구들(claude-replay, mindwalk, zoetrope, claude-code-log)은 **뷰어**라서 사람이 찾아가야 합니다.
sessionreel은 **보내는 물건**을 만듭니다.

영상의 모든 장면은 로그에서 그대로 옵니다.

| 장면 | 로그의 출처 |
|---|---|
| 요청 | 이 작업을 시작한 프롬프트 |
| 탐색 | 첫 수정 전에 읽은 파일과 검색 |
| 실패 | 실패가 찍힌 테스트/빌드 명령 (`pytest`, `jest`/`vitest`, `go test`, `cargo test`, `tsc`, `ruff`, `mypy`, `make <target>`) |
| 수정 | 그 실패와 같은 검사의 다음 통과 사이에 Claude Code가 기록한 diff |
| 통과 | 같은 검사의 성공 |
| 배포 | 성공한 `git commit`/`git push`/`gh pr create`/publish와 커밋 메시지 |
| 숫자 | 실제 작업 시간(15분 넘는 공백은 제외), 도구 호출, 바뀐 파일·줄, 테스트 |

실패→수정→통과 흐름이 없으면 가장 큰 수정으로 영상을 만듭니다. 여러 작업이 섞인 긴 세션이면
그중 **한 에피소드**(수정으로 이어진 요청부터 다음 요청 전까지)만 보여줘서, 다른 작업의 요약으로
끝나지 않게 합니다. 전체를 원하면 `--whole`.

## 설치

```
uvx sessionreel                   # 설치 없이 실행
pipx install sessionreel          # 설치
```

Claude Code 플러그인으로 쓰면, 작업한 에이전트가 직접 자막을 씁니다:

```
/plugin marketplace add mandu5/sessionreel
/plugin install sessionreel@sessionreel
/reel
```

## 사용법

```
sessionreel list                     # 최근 세션 목록
sessionreel 5e55a0d0                 # 세션 id 앞자리 또는 .jsonl 경로
sessionreel demo                     # 내장 샘플 세션 (로그 없어도 됨)
sessionreel --format tall            # 1080×1920 (쇼츠/릴스), wide = 1920×1080
sessionreel --voice                  # OS 음성으로 내레이션 (say / espeak-ng, 클라우드 TTS 없음)
sessionreel plan -o storyboard.json  # 스토리보드를 JSON으로 → 자막 수정 → sessionreel render storyboard.json
```

M1 Pro 기준 35초 1080×1080 영상 렌더링에 약 30초, 파일 크기 약 1 MB입니다.

## 개인정보

가리기(redaction)는 스토리보드가 만들어지기 **전에**, 파싱된 세션 전체에 적용됩니다. 이후 단계는
원문을 볼 수 없습니다. Anthropic·OpenAI·GitHub·AWS·Slack·Google·Hugging Face 키, JWT, Bearer
토큰, 개인 키, `SECRET=값` 형태의 할당, URL 속 자격증명·토큰, 이메일, 홈 디렉터리(→ `~`)를
지우고, `.env*`, `*.pem`, `*.key`, `id_*` 같은 파일의 내용은 아예 보여주지 않습니다. 몇 개를
지웠는지 종류별로 출력합니다.

패턴 기반이라 완벽하지 않습니다. **올리기 전에 영상을 꼭 한 번 보세요.** 어디에도 업로드하지
않고 네트워크 호출도 없습니다.

## 라이선스

MIT. 포함된 폰트는 SIL Open Font License 1.1 (`src/sessionreel/fonts/`).
