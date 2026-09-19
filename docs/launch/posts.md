# Launch copy — sessionreel 0.1.0

Rules learned from 2026 data (see the author's research notes): the video is the post; the
number goes in line one; post where the audience already is; answer the three standard attacks
("what's the use case", "it's a screen recording", "prove it") in the first reply.

## X / Threads (English) — attach docs/demo.mp4 natively, not a link

> My coding agent fixed a bug in 2 minutes. Showing someone took 20.
>
> So I built sessionreel: one command turns a Claude Code session log into a 35-second video —
> the ask, the failing test, the diff, green, shipped. Local, secrets redacted, no API key.
>
> uvx sessionreel
> github.com/mandu5/sessionreel

Reply 1 (answer the attacks up front):
> Not a screen recording — every frame is drawn from the log Claude Code already writes
> (~/.claude/projects). You can make a reel of a session from last month. Nothing is uploaded;
> redaction runs before anything is drawn. Watch it before you post it.

## GeekNews (Show GN) — first-person, story first

Title (site prepends "Show GN:"):
> sessionreel – Claude Code 세션 로그를 35초 영상으로 만드는 도구

Body:
> 에이전트가 두 시간 동안 버그를 고쳤는데, 그걸 팀에 보여주려면 30 MB짜리 로그를 넘겨줄 수밖에
> 없더라고요. 기존 도구(claude-replay, mindwalk 등)는 뷰어라서 상대가 직접 열어봐야 합니다.
>
> 그래서 로그를 읽어서 "요청 → 실패한 테스트 → 고친 diff → 통과 → 커밋"을 30~60초 영상으로
> 만드는 CLI를 만들었습니다.
>
> - `uvx sessionreel` 한 줄. 로컬에서 Pillow로 그리고 ffmpeg로 인코딩, 네트워크 호출 없음
> - 그리기 전에 API 키·토큰·이메일·홈 경로를 가리고, .env 같은 파일 내용은 아예 안 보여줌
> - 실패→수정→통과 흐름을 로그에서 찾아서 스토리를 짬 (LLM이 지어내는 부분 없음)
> - 긴 세션은 그중 한 에피소드만, 한국어 자막(`--lang ko`), 쇼츠용 세로(`--format tall`), OS 음성 내레이션
> - Claude Code 플러그인으로 쓰면 작업한 에이전트가 자막을 직접 다듬음 (`/reel`)
>
> 로그만 있으면 한 달 전 세션도 영상으로 만들 수 있습니다. 올리기 전에 한 번은 꼭 보세요 —
> 가리기는 패턴 기반입니다.

## Hacker News — NOT from the author's account (karma 1, auto-flagged before)

If someone else posts: title
> sessionreel: turn a Claude Code session log into a 35-second video

## r/ClaudeAI / r/ClaudeCode — video post

> I made a CLI that turns a Claude Code session into a 35-second recap video (local, redacted)
