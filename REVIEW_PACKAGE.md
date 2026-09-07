# 独立审查包

本 PR 不跟踪二进制 ZIP。独立审查请直接查看 PR 中的源码、测试、JSON、日志和 PGN；这些文件均为
独立文本文件。原本被全局 `*.pgn` 规则忽略的本任务 PGN 已显式纳入 Git，不依赖 ZIP 保存证据。

如需离线传递，可在 checkout 后运行 `tools/package_review.sh`，在本地重新生成
`artifacts/nullgambit-numba-review.zip` 及其 `.sha256`。该路径被 Git 忽略，不会出现在 PR；它不是
比赛提交包，不能上传到比赛平台。压缩包由当前 Git 跟踪内容构建，包含根目录稳定源码、Numba 候选、冻结 Zaw 基线、
`pyproject.toml`/`uv.lock`、测试、harness、对战工具与开局集、`STATUS.md`，以及所有已跟踪的原始
JSON、日志和 PGN。Git 虚拟环境、缓存、`.git` 元数据和任何未跟踪凭证都不在包中。

校验本地重建产物：

```bash
sha256sum -c artifacts/nullgambit-numba-review.zip.sha256
```
