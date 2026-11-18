# 自适应批次试验的回放与条件检验

README.md 记录已运行的固定计划工作流。扩展 `trial.archive.TrialArchive`，让分析员使用同一归档保存按响应调整分配的试验及其条件报告。

## 设计与回放

- `save_adaptive(initial_a, initial_b, horizon, min_n, boundary)` 登记一份不可变设计，返回正整数 `design_id`。每次合法登记产生独立身份。初始球数和界值均为正整数，且 `2 <= min_n <= horizon <= 18`。所有整数参数均排除布尔值。
- `replay_adaptive(design_id, responses, assignments)` 以明确设计和整段实际记录创建回放。`responses` 是按到达顺序排列的列表或元组，每项为非布尔整数 0 或 1。`assignments` 是由 A、B 组成的字符串，或包含这些单字符的列表或元组。两序列必须同长，位置从 1 起，响应分别绑定该位置的批次。合法记录必须恰好结束于首次达到的停止时点。

每步按当前球数比例分配，成功给本臂加球、失败给另一臂加球。分配概率在本步响应影响球数之前取得。S 从 0 开始，A 成功加 1，B 成功减 1，失败保持 S。处理完该批次后，从第 `min_n` 批起，首次满足 `abs(S) >= boundary` 即停。若此前未停，到 `horizon` 时停止。

回放以字典返回。`id` 是回放身份，`design_id` 是确切父设计身份，`design` 为含 `initial_a`、`initial_b`、`horizon`、`min_n`、`boundary` 的字典。`responses`、`assignments` 都返回有序列表。`steps` 为按位置排列的字典列表，每项有 `position`、`before`（分配前 A、B 球数列表）、`probability`（实际分配的 Fraction 概率）及 `statistic`（本步完成后的 S）。顶层 `path_probability` 为全部实际分配概率之积，`statistic` 为最终 S。

## 停止长度条件化

`test_adaptive(replay_id)` 消费指定回放。尖锐零假设下，同一批次在所有反事实分配下维持其已观测响应，后续球数、分配概率、S 和停止资格则按该反事实历史重新确定。设回放实际含 n 批，只计首次终结于 n 的路径。此前已终止的路径和 n 批后仍能继续的路径都不计入。只需已观测响应，不请求 n 之后的数据，也不对未来响应建模。

报告返回字典，`id` 为报告身份，`replay_id` 为父回放身份，`observed_statistic` 为实际最终 S。`stop_mass` 是 P(N=n)，`joint_tail_mass` 是 P(N=n 且 |S|≥|S_obs|)，`conditional_tail` 是后二者中联合质量除以停止质量。三项均为 Fraction，尾部包含等号。分配回放向检验交接反事实历史的概率及首次终结资格，使两种质量基于同一个终结事件。允许完整枚举和全量重算。

## 保存与复核

`read_adaptive_replay(replay_id)` 和 `read_adaptive_report(report_id)` 按各自的输出格式返回保存值，读取无需重走路径或重做检验。身份在各自入口内为正整数且排除布尔值，格式非法抛 ValueError，合法但不存在的身份抛 KeyError。无效设计、长度不符、未达终止即结束、终止后继续提交或非法记录抛 ValueError，整次不发布。

用 `replay_adaptive` 再提交一份合法记录即可登记更正，引用原设计或另一明确设计均可。修改调用时的输入列表或返回值、登记更正以及关闭重开，都不得改变已保存的旧成果。每次发布沿用 V1 原子失败边界。可以用既有 `archive.publication.fail_at('report_header')` 核验新报告写入后回滚，原回放和旧报告仍可读取，重试可正常产生报告。旧数据库可继续打开，保留固定设计的 Python 接口、CLI、交付包及全部原测试。新增成果通过上述读取接口交接。

## 样例与运行

`examples/adaptive_cases.py` 给出固定输入与手算期望。初始球数 (1,1)、四个成功、实际 AAAA 的回放质量是 1/5，S 为 4。最少批次及界值均为 4，上限为 4 时三项报告质量为 1、2/5、2/5。只把上限改为 6 时，恰好在 4 批终结的只有 AAAA 和 BBBB，三项质量为 2/5、2/5、1。最少批次和界值均为 2、上限为 4 时，实际 ABAA 在第 4 批终结，早在第 2 批终结的 AAAA 不参加该报告。样例另含混合响应及更正后读回。

实现后在项目根目录用 `python3 -B -m examples.adaptive_cases` 运行固定样例。补独立的短路径核账及交接不变量说明。沿用 `.pointwise-runtime.json` 的 version 1、cli 运行方式，setup 是准备命令的 argv 列表，verify 和 demo 各为可执行的 argv。verify 须包含原回归及新能力业务核验，任一检查失败须非零退出。demo 须展示真实条件报告及更正后读回旧成果的结果。
