# 冻结候选竞技验收进行中（2026-09-10）

[Linux 固定批次 34482804548](https://github.com/ThantZaw-cs/nullgambit/actions/runs/34482804548)
已实际进入40局10+0.1，工作流提交1780e14。候选311284…da221，TT+LMR均开，对手v7 aba3db…1b3d。
已有正确性、独立局面、残局、Linux兼容性与比赛ZIP全部复用，没有调参或重跑。
原08:28 UTC开局、顺序、时控、600总plies和2400/6000秒内部执行封顶未变。
第一局前记录：完整40局、零失败/VOID、得分率>=50%即自动进入原正式20局120+0.5。
这是继续测试的门槛，不是棋力提升或统计显著声明。独立留出中性已获用户明确接受继续实战。
三小时预算保守从12:36:03 UTC计，截止15:36:03；此前未观测时段未归因、未扣除或重置。
本阶段只改验收工作流与门禁证据，不改源码、裁判、原开局，不公开私有材料。
最终计数以下载后的完整逐局PGN/棋钟审计为准；不能根据进行中片段决定停赛。

以下为上一阶段保存的历史状态，当前竞技执行以 ACCEPTANCE.md / acceptance-state.json 为准。

---

# astra-v8-search 精确继续位置

2026-09-10 12:03 UTC最终状态：开发与效率支持继续验证，独立结果近中性，
尚未证明净棋力提升，保留v7。正确性和Linux兼容性均通过；剩余预算不足完整固定批次，
因此本轮快棋0/40、正式0/20。对战gate仍false表示尚未放行，不是程序门禁失败。
获得新增执行预算后，优先继续同一冻结组合的原40局快棋，再有支持才原20局正式对照。
不调参、不开新候选，也不重跑已完成且哈希相符的开发/留出/Linux结果。

## 先核验现场与真实状态

- 工作树：`/private/tmp/nullgambit-v8-search-20260910`；分支 `astra-v8-search`。
- 选择提交 `74ebe2b`；后续 `046a925` 只触发冻结默认的兼容性检查。
- 候选 `prototypes/search_core/agent.py`：
  `31128444d171cc2526c99ff13cb92da43ad89ada9d99d14ec4bd53a0cc4da221`，默认 TT+LMR。
- 对手 `baselines/online_v7/agent.py`：
  `aba3db18ebe424b2025b3d967b88057b6ad242978cc328accc1642e2c8a91b3d`。
- 保留 `freeze.json`、全部负面/中断记录及前代冻结版本。不能将源码换成仓库根旧 agent。
- [冻结默认 CI 34472928110](https://github.com/ThantZaw-cs/nullgambit/actions/runs/34472928110)
  已实际成功，86测试/ruff/mypy/最终默认组合ZIP和独立runner均通过。
  读取`LINUX_SELECTED.md`及artifact即可，不重新触发；兼容性不是棋力证明。
  [主要 Linux 测量 34470325484](https://github.com/ThantZaw-cs/nullgambit/actions/runs/34470325484)
  已成功，不重跑也不把复测样本并入其 168 行。

私有原始结果目录：
`/Users/chris/Projects/nullgambit-astra/data/online/teacher-v8/`。
`development-fixed/` 已完成 192/192；`development/` 是已停的缺陷版 170/192，不能续成有效结果。
`holdout/` 因工具未严格反序而在读老师答案前停止，79/96行作为方法缺陷保留，不续跑。
`holdout-balanced/` 是同一冻结候选、同一24局面与棋钟的严格反序测量，已完成96/96；
**96次测量与全部老师标签均已完成，不重跑、不再补同一批。**
先核对 `stage.json`、`runs.jsonl`、标签文件与具体进程，避免重复启动现存任务；
只操作已识别的相关 PID，不全局杀进程。
该目录、线上原件、老师与标签不提交公开仓库。

## 已完成留出：近中性，保留同一冻结候选

`holdout-summary.json`是最终结果：v7平均老师损失48.542cp，组合52.000cp，增损3.458cp；
双方>=100cp失误均6/48调用、3局面，24位置全部在±50cp近似等价范围内，无明确净收益。
P21的2M初判+78cp在冷根/双方走法4M复核后变+1cp；保留初判文件，不能继续声称稳定回退。
其余23位置为2M标签，P21为4M，所有标签来自同一老师和完整历史；不把小样本说成统计证明更弱。
16个已见残局64调用也已完成，每边32/32保持WDL，无质量提升，结果见`endgame-summary.json`。

完整留出测量输入是：
`/Users/chris/Projects/nullgambit-astra/data/online/teacher-v6/private/human-b-holdout-positions.jsonl`，
SHA-256 `a59dc5a2c7a34359a8bb388034a9a2d0d6bf6583bf73a961195a60b87f45a35b`。
`holdout-balanced/`、其 command/exit 文件、最终匿名聚合与4M复核均应保留；
`holdout/`的79条是顺序缺陷记录，不能与最终96条拼成更多样本，也不能再续跑。

**禁止在本次已读留出上调参后重复刷分，或换配置用同一留出挑赢家。**
P21复核取消了原先的>50cp退步，最终没有明确新的大失误；这不要求把近中性结果判成失败，
也不证明更强。开发与效率已有继续验证的信号，无需再造留出或新TT候选。

下面是**用户提供新增执行预算后，同一冻结TT+LMR候选**的固定对战继续步骤。
先审阅并记录已经通过的正确性、开发与近中性独立结果，再明确放行原40局快棋；
不得仅为让工具启动伪造证据。它们不是本轮余下几分钟内待自动执行的命令。

## 固定40局快棋：尚未开始

使用原 `fast-plan.json` 的 20 个开局，每个换色，总计 40 局，10+0.1，对冻结 v7。
**不得重新生成 `opening-selection.json` 或更换开局/顺序。**
计划已绑定311284…da221；candidate_frozen、correctness_passed、development_positive
为true，holdout_passed和fast_screen_passed仍为false，明确阻止本轮启动。
新增预算后，先复核已通过的正确性/开发及近中性独立结果，明确记录是否放行holdout_passed；
保留同一源码、原开局数组、局数、时控和封顶规则不动，提交这一实际验收决定。
`fast_screen_passed` 在对战完成前保持 false。

从已核对的 checkout 使用 Python 3.12、锁定依赖。以下 Linux 命令只应在这些 gate 已通过后执行，
输出目录必须尚不存在；两边独立进程，固定同一 CPU、线程数1、2 GiB地址空间，整个批次只跑一次：

```bash
uv sync --locked
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMBA_NUM_THREADS=1 MKL_NUM_THREADS=1
V8_TEST_CPU=$(uv run --no-sync python -c 'import os; print(min(os.sched_getaffinity(0)))')
ulimit -v 2097152
timeout --signal=TERM --kill-after=30s 41m taskset -c "$V8_TEST_CPU" uv run --no-sync python -m tools.v8_match --plan benchmarks/astra-v8/fast-plan.json --out artifacts/v8-search/fast
uv run --no-sync python -m tools.summarize_v8_matches artifacts/v8-search/fast
```

原计划内部封顶 2400s，外部 41m 用于安全清理；程序逐局保存 PGN、逐步棋钟、结果、失败及 VOID。
600总plies含开局仍未自然结束记和棋，不以子力判胜。
结果解释必须审计完整40局与20配对，报告失败/VOID、最坏开局和不确定性；不能只报告领先片段。
不因领先停、不因输了重跑。中断局作为 VOID 保留。只有 `results.json` 为 incomplete、
无 pending_game、尚有未排定局且原封顶仍有剩余时，才可对同一输出目录加 `--resume`；
计划必须逐字节相同，已完成或中断的颜色/开局永不重放，已用执行时间不会清零。

## 快棋过筛后：唯一20局Linux正式对照

本轮正式对照0/20且不启动。新增预算后，只有同一冻结组合的完整快棋结果支持继续、
无未解释故障时，才更新原`formal-plan.json`的通过证据，
包含 `fast_screen_passed`；不能修改已经固定的另10个开局，不能用快棋开局替代。
正式要求 Linux x86_64 / Python3.12、锁定依赖、同资源，120+0.5，共20局，内部封顶6000s。
这需要新的足够执行预算；本轮12:15:18 UTC截止不能自动延长。

复用 `.github/workflows/v8-search.yml` 的显式 formal 路线：
将完整已审计的40局匿名汇总保存到 `benchmarks/astra-v8/`，在 `ci-trigger.json` 中写 phase=formal、
相同候选 SHA、formal_plan_sha256、fast_summary_path 与 fast_summary_sha256。
只提交并推送 `astra-v8-search`，该触发提交消息包含 `[v8-formal-once]`。
CI 需要全部 gate、完整40局、同源哈希、0失败/VOID、首次 run_attempt 才会进入正式步骤；
不能伪造 gate 绕过这些检查。工作流不是 workflow_dispatch，只有该分支中触发文件的 push 生效。

正式步骤等价于：

```bash
timeout --signal=TERM --kill-after=30s 101m taskset -c "$V8_TEST_CPU" uv run --no-sync python -m tools.v8_match --plan benchmarks/astra-v8/formal-plan.json --out artifacts/v8-search/formal
uv run --no-sync python -m tools.summarize_v8_matches artifacts/v8-search/formal
```

若首批正式对战不理想，保留完整结果并停止发布，不能重新跑同批直到赢。
Actions 重试不会自动重开正式对战；基础设施中断只能依据原检查点、原剩余封顶继续未排定局。
运行后的 ZIP 只作为 Actions artifact，检查根目录候选 agent.py 的打包前后哈希与独立runner。
不合并、不中途改评分、不自动上传比赛；v7 保持可回退且在完成正式验收前继续保留。
