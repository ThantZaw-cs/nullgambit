# 首次接管与基线验证状态

日期：2026-09-06（UTC）

## 基线身份与范围

- Zaw 原版基线 commit：`fe9bf59e386340e25e617db2682afaa4d8988932`（分支 `work`，提交说明
  `Add classical chess engine and validation suite`）。本轮开始时工作区干净。
- 本轮没有修改 `agent.py`、`harness/`、裁判逻辑或评分规则，也没有上传比赛、推送或合并。
- 已阅读 `AGENTS.md`、`README.md`、`agent.py`、`pyproject.toml`、`uv.lock`、`Makefile`、现有
  `tests/`、`benchmarks/`、`tools/` 与 `harness/`。依赖以 `pyproject.toml`/`uv.lock` 为准，使用
  `uv sync` 安装/核对。
- 按仓库要求尝试读取线上 canonical 文档。浏览工具返回 HTTP 401；随后直接执行
  `curl -fsS --max-time 20`，`agent-contract.md` 和 `rules.md` 均返回 HTTP 403（退出码 22，
  未取得正文）。因此本记录不把仓库 quick reference 中会变化的数字重新宣称为线上最新规则；
  下一次涉及上传或限额决策前，需要允许该环境访问上述 URL，或由站点解除鉴权/反爬限制后重试。

## 已有算法（不是本轮重写）

当前 `agent.py` 是一个可读的经典搜索引擎，主要组成如下：

1. `python-chess` 负责 FEN 和合法走法生成；入口为 `get_move(fen, time_left_ms) -> str`。
2. 迭代加深 negamax/alpha-beta，保留最后一个完整深度的最佳着；带 principal variation
   search、将军延伸、保守 late-move reduction、killer/history 排序。
3. 静态搜索会搜索吃子、升变，并在被将军时搜索全部应将；包含将死距离处理。
4. 评价为子力与按阶段插值的 piece-square table，加双象、兵型（孤兵、叠兵、通路兵、连接兵）、
   车开放线、王翼兵盾和王区压力。数值评价与攻击图由 Numba 在 import 时预编译。
5. 有上限为 20,000 项的跨回合置换表；缓存键包含局面、五十回合计数及重复局面上下文。
6. 通过保存上一回合棋盘恢复对手一步，从只有 FEN 的接口中尽量保留同一局的重复历史。
7. 时间管理按剩余时间分配单步预算（最高 2.5 秒，并预留响应/回溯余量）；极低时间直接返回
   生成器给出的首个合法着，避免启动搜索。

## 实际执行的命令与结果

### 环境与依赖

- `git rev-parse HEAD`：成功，得到上述基线 commit。
- `git status --short --branch`：开始时为 `## work`，无未提交改动。
- `make setup`（实际调用 `uv sync`）：成功；解析 26 个包，审计 24 个包，无安装错误。

### 静态检查与现有测试

- `uv run python -m unittest discover -s tests -v`：成功，**32/32** 通过，耗时 0.861 秒。
  覆盖双方一步杀、静态搜索、王车易位、吃过路兵、升变/低升变、超时回溯、低时钟、重复局面、
  五十回合、置换表容量/将死距离、攻击图和多项评价性质。
- `uv run ruff check .`：成功，输出 `All checks passed!`。
- `uv run mypy`：成功，输出 `Success: no issues found in 15 source files`。

### 少量短局

- `uv run python -m harness.arena --opponent baselines/random --games 2 --base-ms 5000`：成功完成
  两局，没有 crash、illegal 或 flag；本 agent 两局均以将死获胜（`+2 =0 -0`）。这只是协议和完整
  对局冒烟测试，样本极小且对手是 random，**不能据此判断或声称棋力提升**。

### 合法走法、异常和低剩余时间探针

- 用内联 Python 脚本对初始局面、可王车易位局面、升变局面、吃过路兵局面分别传入
  `time_left_ms = 0, 1, 5, 10, 50`，共 20 次调用：20/20 均返回可由
  `chess.Move.from_uci` 解析且属于当前 `legal_moves` 的着法，无异常。
- 0--10 ms 的实测调用均在 0.20 ms 内返回；50 ms 探针均在 1.50 ms 内返回。这里只记录本机一次
  观测，不将其视作其他机器上的实时保证。
- 非法 FEN `not-a-fen`：已验证抛出 `ValueError`（`expected 8 rows ...`）。这不是合法合约输入，
  但说明入口不做容错包装。
- 已结束的将死局面：已验证返回字符串 `0000`，无异常。代码和裁判约定不会向结束局面请求走法；
  若外部调用方违反该前提，`0000` 不是棋盘上的合法着。
- `uv run python -m tools.benchmark --seconds 0.05 --out /tmp/nullgambit-benchmark.json`：成功跑完
  10 个开发局面；相对 `classical_v2` 的中位 NPS 比为 **0.99x**。0.05 秒窗口噪声很大，只用于
  确认 benchmark 可运行，不据此判断速度回退或棋力。

## 已验证的问题

1. **线上规则文档在当前环境不可取。** 两条 canonical URL 经浏览工具为 401，经 `curl` 为 403。
   在恢复访问前，无法验证仓库内规则常量是否仍与线上完全一致。
2. **入口对非法 FEN 不容错。** 实际调用会抛出 `ValueError`。合法比赛输入不触发它，所以目前不把
   它定性为比赛缺陷。
3. **结束局面返回 `0000`。** 已实测；这符合当前代码所写的裁判前提，但不是一个合法棋步。

未发现现有 32 项回归、ruff、strict mypy、20 个低时钟合法性探针或两局短局中的 crash、非法走法、
超时败或棋盘回溯损坏。

## 尚待验证的怀疑

1. 现有 benchmark/对局报告来自不同源码哈希与有限样本；它们可用于理解历史，不能直接证明当前
   commit 对未知开局或强对手的真实胜率。
2. 静态搜索对所有吃子展开到固定深度，尚无 SEE/delta pruning。在战术密集局面中可能发生节点
   爆炸、导致迭代加深少完成一层；本轮短局和 0.05 秒 benchmark 不能验证该怀疑。
3. 置换表包含完整重复上下文，正确性较保守，但键可能偏大并降低命中率；尚无内存峰值、命中率与
   棋力收益的隔离实验。
4. 本地环境是 Python 3.14，而项目目标为 Python 3.12；本轮通过不能替代平台固定版本上的上传验证。

## 下一轮最值得做的一项改进

**为静态搜索加入可读、保守的 SEE/delta pruning（先补战术等价与超时回溯回归），再以相同源码哈希、
配对换色的 holdout 对局验证。** 理由是它直接针对固定深度吃子搜索可能产生的节点爆炸，有机会在相同
时限完成更深迭代；同时必须用现有 poisoned capture、升变、将军应对测试及新增边界用例防止错误剪枝。
在达到足够配对样本前，只报告节点数、完整深度和置信区间，不宣称棋力提升。

---

## 自主改进阶段：候选 1（2026-09-06）

### 基线保护与环境

- 已核对接管提交 `d260996ddd91e560eb3fa036245360d8a7c0fe11` 与 Zaw 基线
  `fe9bf59e386340e25e617db2682afaa4d8988932`。通过 `git show fe9bf59:agent.py` 冻结到
  `baselines/zaw_original/agent.py`；冻结文件与候选修改前根目录 `agent.py` 的 SHA-256 均为
  `887d8ca093d429d305cac98272d28447611bdcf07ac25ab5174c41ca6b6018f5`，逐字节 diff 为空。
- 尝试 `uv sync --python /usr/bin/python3.12`。解释器 Python 3.12.3 存在，但所需 cp312 的
  `numpy==2.5.2`、`torch==2.13.0+cpu`、`numba==0.67.0`、`librt==0.15.0` 不在本地缓存，下载经
  3 次重试均因 `tunnel error: unsuccessful` 失败。没有继续尝试网络；随后以
  `uv sync --python /root/.pyenv/shims/python3.14 --offline` 恢复 Python 3.14.4 环境。因此 3.12
  兼容性仍未在本机复测。

### 瓶颈测量

- 固定随机种子 `20260906`，从 29 个确定性随机对局中间局面直接运行深度 8 静态搜索。Zaw 基线
  合计 5,508 节点、324.52 ms，中位 68 节点，最坏局面 1,781 节点/118.56 ms；结果保存在
  `benchmarks/quiescence-baseline.json`。少数局面形成明显长尾，支持“静态搜索偶发膨胀”的方向，
  但总耗时还包含 Python 走法生成，不能认为节点剪枝会等比例提速。

### 唯一改动与回归

- 候选 1 仅加入一项改动：非将军节点中，若非升变、非将军的吃子即使获得被吃子价值再加 200 cp
  余量仍不能提高 alpha，则跳过该吃子。升变、将军和吃过路兵均有明确保护/测试。
- 同一 29 局面复测为 4,223 节点、317.19 ms，节点为基线的 76.67%，29 个根静态搜索分数全部
  相同；墙钟仅减少约 2.3%，说明 `board.gives_check()` 等判断开销抵消了大部分节点收益。原始数据
  在 `benchmarks/quiescence-delta.json`。
- Python 3.14.4 下完整 unittest 为 33/33 通过；新增 delta 边界测试，并保留既有战术、被将军时
  安静应将、升变/低升变、吃过路兵和超时回溯测试。`ruff check .` 与 strict `mypy` 均通过。

### 40 局快速筛选（不是棋力证明）

- 固定 `1,000 ms + 50 ms/步`，候选与冻结 Zaw 基线逐局同开局换色：development 20 局为
  `+11 =1 -8`，confirmation 20 局为 `+7 =5 -8`；合计 `+18 =6 -16`、52.5%，失败 0。
- 以每个换色对的平均得分为单位做固定种子 200,000 次 percentile bootstrap，20 对的 95% 区间
  为 **42.5%--62.5%**，包含 50%。报告及源码哈希保存在
  `benchmarks/delta-screen-development.json` 与 `benchmarks/delta-screen-confirmation.json`；PGN 已由
  工具生成但按仓库 `.gitignore` 不纳入版本控制。
- 结论：候选没有显示伤害，但节点收益未转化为清晰墙钟或对局优势，证据不足，**不宣称优于基线，
  不扩大到 100--200 局，也不消耗 holdout 最终验证集或正式时控预算**。候选已保存为提交 `276ab79b141c7b87e167479839b132696c828555`。随后已恢复根目录
  `agent.py` 为冻结稳定版；候选可通过该提交单独复现。

## Numba 搜索内核路线（2026-09-07）

### 里程碑一：编译棋盘内核

- 新原型位于 `prototypes/numba_kernel/`，根目录稳定版 `agent.py` 未改。实现是原创的 64 格有符号
  `int8` 棋盘，加独立的行棋方、王车易位权、吃过路兵格、半回合与全回合状态；伪合法生成、攻击
  检测、合法性过滤和 make/unmake 均在 Numba nopython 路径中。
- 初始局面 perft 1--4 层为 `20, 400, 8902, 197281`；复杂含王车易位局面 1--3 层为
  `45, 1947, 85877`，均与 python-chess 参照一致。
- 固定种子 `20260907` 生成并逐一核对 1,000 个合法局面，合法 UCI 集合全部一致。另覆盖双方王车
  易位、吃过路兵、四种升变、被将军、将死与逼和；固定种子下 300 个局面的每个合法着均完成
  make/unmake，棋盘及全部五个状态字段逐元素恢复一致。
- 完整测试为 36/36 通过。首次 Numba import/预热在本机约 8.1 秒，属于编译耗时，不计作正常生成
  耗时。里程碑一正确性门已通过，可以进入搜索原型；Python 3.12 仍因上一节所述依赖阻塞未验证。

### 里程碑二：搜索原型检查点（尚未完成）

- 在同一编译棋盘上接入迭代加深、alpha-beta、吃子/升变静态搜索、MVV-LVA 类排序、根节点前次
  最佳着排序和 PVS；叶节点评价直接调用原版两个 Numba 评价函数，未改变评价参数。每 1,024 节点
  读取真实 `time.monotonic()`，超时逐层 unmake 后返回上一完整深度着法；0.05 秒测试实际在 0.15 秒
  门限内返回合法备用着并保持输入棋盘不变。
- 不带排序/PVS的首版虽然单节点快，但分支过多：五个开发局面固定深度 2、3 的中位耗时分别是原版
  的 1.45 倍和 3.15 倍。该负结果保存在 `benchmarks/numba-kernel-search.json`，证明“编译后 NPS 高”
  本身不能带来有效深度。
- 加入排序后，固定深度 2/3 的代表性中位耗时约为 23.31/156.22 ms（原版此前同批为
  82.49/309.76 ms）。最终 PVS 版本在五个开发局面上的平均完整深度为：0.25 秒
  `3.0 vs 2.4`、1 秒 `3.8 vs 3.0`、2.5 秒 `4.4 vs 3.8`（Numba vs 原版）。逐局结果、源码哈希、
  实际墙钟与节点数保存在 `benchmarks/numba-kernel-pvs-search.json`。
- 战术检查覆盖一步杀、毒兵拒吃、后升变和吃过路兵，均返回预期合法着；完整 unittest 为 38/38，
  ruff 与 strict mypy 通过。该进程同时载入原版与原型后的峰值 RSS 约 299 MB；完整生成与搜索预热
  约 19.46 秒，低于仓库记录的初始化预算，但 Python 3.12/平台仍未验证。
- **尚未实现的正确性条件：**置换表、搜索路径及跨请求的三次重复历史、将死分数的 TT 距离换算。
  五十回合叶节点已经处理，但上述缺口意味着里程碑二尚未通过，原型不能晋升比赛候选。
- 因正确性门未通过，本轮严格停止在里程碑二，没有进入 10 秒配对赛，也没有消耗 holdout 或正式
  时控验证集。当前数据说明这条路线值得继续投入一个受限阶段：下一步只实现重复历史与有界 TT，
  重跑同一正确性/深度门；通过后才进行里程碑三对战。稳定版 `agent.py` 仍保持原样。

### 安全对局补齐与第一轮实战（2026-09-07）

- 原型现已自带原版的 Numba 评价实现，移除 `import agent as stable_agent`。通过真实
  `harness.runner` 从 `prototypes/numba_kernel` 独立启动并完成走法，确认比赛式 `import agent`
  不会误导入根目录稳定版，也不依赖仓库根目录的 `agent.py`。
- 搜索路径加入三次重复检测；`get_move` 用上一请求棋盘恢复对手一步，使跨请求历史进入搜索。
  重复键只在存在**合法**吃过路兵时计入 EP 格。补齐五十回合、子力不足、最大 64 ply 保护，并保持
  “无合法着先判将死/逼和，再判其他和棋”的优先级。定向测试覆盖三次重复、不可用/被钉住 EP、
  五十回合与将死冲突、子力不足及所有状态的超时恢复。
- TT 是固定 65,536 槽的 direct-mapped **仅走法缓存**，跨迭代用于排序，不缓存分数；因此不会在
  不同半回合计数或重复历史间误用分数，也不存在要换算的 TT 将死距离。本轮明确不宣称完成分数 TT。
- 真实入口 `get_move` 对 1、5、10、50、100、500 ms 各重复 5 次，30/30 合法且均在传入剩余时间内
  返回；最慢分别约 0.340、0.067、0.067、0.094、0.063、0.083 ms。低钟不进入编译搜索，解析、
  历史与 UCI 返回均包含在计时内。独立进程完整预热实测约 27.88 秒，全部发生在 ready 前。
- Python 3.14.4 下完整 unittest 为 **44/44**，ruff 与 strict mypy 通过；Python 3.12 依赖仍不可用，
  本轮按要求没有再次尝试下载。根目录 `agent.py` 和冻结 Zaw 文件仍具有相同 SHA-256
  `887d8ca093d429d305cac98272d28447611bdcf07ac25ab5174c41ca6b6018f5`。
- 最终候选源码 SHA-256 为 `7ffb2370d69dbbf906551bc8892a5197f29670f6a27261ba082f12241b5a5142`。
  10 秒 + 0.1 秒的 20 个不同开局逐一换色共 40 局：development `+15 =4 -1`，confirmation
  `+15 =3 -2`；合计 **+30 =7 -3，83.75%，失败 0，VOID 0**。两批串行墙钟分别 16m00.148s 与
  15m32.811s。以 20 个换色对为单位、固定种子 200,000 次 bootstrap 的 95% percentile 区间为
  73.75%--92.5%。JSON、完整 PGN 与日志保存为 `benchmarks/numba-kernel-game-*`。
- 同一候选随后按 120 秒 + 0.5 秒从 Ruy Lopez 做一对换色复测：**+1 =0 -1，失败 0，VOID 0**，
  墙钟 7m01.826s。两局只能说明完整时控可运行，不能证明正式时控更强；报告、PGN 与日志保存为
  `benchmarks/numba-kernel-formal-smoke.*`。未使用 holdout 开局集。
- 结论：快速配对结果和正式时控可运行性足以支持继续投入，但仍保持为独立候选，不覆盖稳定版。
  下一步应在未使用的 holdout 上扩大正式时控配对，并评估加入历史兼容的分数 TT 是否还有净收益。

## 正式时控验收与审查整理（2026-09-07）

- 请求核对的历史提交 `bb03c74` 在当前仓库中已无法解析（`git rev-parse`/`git show` 均报告 unknown
  revision；环境中的历史已聚合为 `2f9f0c3`）。没有用其他版本冒充它。上一轮 `+30 =7 -3` 两份
  原始 JSON 记录的候选 SHA-256 均为
  `7ffb2370d69dbbf906551bc8892a5197f29670f6a27261ba082f12241b5a5142`，与本轮冻结候选逐字节一致；
  对手哈希仍为 Zaw/`fe9bf59` 的
  `887d8ca093d429d305cac98272d28447611bdcf07ac25ab5174c41ca6b6018f5`。
- `tools.positions.positions("holdout")` 实测返回 10 个不同名称、10 个不同合法 FEN。不过这些开局已
  存在于源码、测试会读取它们，且仓库原有 `benchmarks/positional-holdout.json` 曾用旧版 agent 跑过，
  所以本轮明确称为 **holdout 套件验收**，不称“从未见过”的盲测；Numba 候选此前未在该套件对战。
- 串行、独立进程、同资源执行 10 个 holdout 开局逐一换色，时控 120 秒 + 0.5 秒，共 20 局且没有
  提前停止。最终 **+9 =10 -1，得分率 70.0%，失败 0，VOID 0**；终止原因为 10 次将死、10 次三次
  重复，墙钟 69m38.545s。完整逐局 JSON 和每局 PGN 在
  `benchmarks/numba-kernel-formal-holdout.{json,pgn}`，命令原始输出及总耗时在同名 `.log`。
- Python 3.12.3 解释器存在；仅尝试一次隔离、离线同步：
  `UV_PROJECT_ENVIRONMENT=/tmp/nullgambit-py312 uv sync --python /usr/bin/python3.12 --offline`。解析锁文件
  后因缓存缺少 `torch==2.13.0+cpu` 的 cp312 wheel 而失败，原文为 `Network connectivity is disabled`
  及 `requested data wasn't found in the cache`。因此 **没有完成 Python 3.12 验证**。最小人工协助是
  向 uv 缓存提供 `uv.lock` 指定的全部 cp312 wheels（至少该 torch wheel），或临时允许访问锁文件中的
  PyPI/PyTorch CPU index；无需改代码或权限绕过。
- 本轮未更改稳定版、搜索算法、评价或 TT；仅新增验收记录与原始产物。正式 holdout 结果支持继续
  候选流程，但仍不能单独保证平台棋力或兼容性，上传前必须补 Python 3.12/平台验证。
