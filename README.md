# 澄河批次试验分析

澄河水处理研发组在每次试验前确定各到达位置的 A 臂分配概率。登记员按批次到达顺序提交处理分配和二元响应。分析员核对实际路径并发布精确随机化报告，工艺负责人可以比较更正前后的证据，复核人员可以用交付包重新核算历史结果。

## 运行

使用 Python 3.11 标准库，在项目根目录运行。

```sh
python3 -B -m unittest discover -s tests -t . -v
python3 -B -m trial.archive demo examples/day.json
```

`demo` 在临时目录中保存公平四步计划及四个成功响应，实际分配为 AAAA。路径质量为 1/16，S 为 4，双尾质量为 1/8。最后一个响应更正为 0 后，新报告 S 为 3、双尾质量为 1/4，原报告保留 1/8。命令关闭并重开会话，导出原报告并在关闭会话后重新核算。

```sh
python3 -B -m trial.archive init trials.db
python3 -B -m trial.archive analyze trials.db examples/day.json
python3 -B -m trial.archive read trials.db 1
python3 -B -m trial.archive export trials.db 1 > report.json
python3 -B -m trial.archive verify report.json
```

`read` 和 `export` 接收 `analyze` 输出的报告 ID。`init` 重复运行会保留已有修订和成果。`analyze` 显式登记输入文档中的设计和记录，每次合法登记生成新修订。CLI 错误写入标准错误并返回非零状态。

## Python 接口

```python
from fractions import Fraction
from trial.archive import TrialArchive
from trial.reconciliation import verify_delivery_bundle
from trial.revisions import BatchRecord

with TrialArchive.open('trials.db') as archive:
    design = archive.save_design('today', [Fraction(1, 3), Fraction(2, 3)])
    records = [BatchRecord('Z', 1, 'A', 1), BatchRecord('A', 2, 'B', 0)]
    revision = archive.save_trial('water-test', design, records)
    replay = archive.replay_fixed(revision)
    report = archive.test_fixed(replay.id)
    saved = archive.read_report(report.id)
    bundle = archive.export_report(saved.id)

verified = verify_delivery_bundle(bundle)
```

`save_design` 接收 1 至 18 个按位置排列的有理概率，包含端点 0 和 1。Python 输入可使用 Fraction 或整数，JSON 输入使用 `['分子', '分母']` 对应的两个十进制文本。数据库和交付包统一使用约分后的同一编码，分母为正数。设计及试验修订均可用返回的值对象或其 `(id, revision)` 键指明。`read_design`、`read_trial`、`read_replay`、`read_binding` 提供确切身份读取。

`save_trial` 接收 BatchRecord 或具有 `batch_id`、`position`、`assignment`、`response` 四个字段的映射。记录按到达顺序提交，位置必须完整覆盖 1 至计划长度，且批次 ID 唯一。分配为 A 或 B，响应为整数 0 或 1。身份须有非空白内容。非法值抛 ValueError，未知的确切身份抛 KeyError。更正通过原入口提交完整记录，可明确引用原设计修订。

回放按位置取 p_i 或 1-p_i，保存全部实际分配概率及其精确乘积。零概率路径拒绝发布。S 为 A 臂成功数减 B 臂成功数。固定零假设保留每个位置的响应，用预定概率累加所有反事实分配的 S 分布。报告的双尾质量包含与观察绝对统计量相等的边界。`analyze_fixed(revision)` 联合发布回放和报告，返回 `(replay, report)`。`replay_fixed` 和 `test_fixed` 也可以分别使用。

成功成果绑定确切设计、试验及回放。`read_report` 检查编码、父链和数值自洽，返回独立副本。`export_report` 生成版本化 JSON 对象。离线入口从包内计划和记录重算路径、统计量、完整分布和尾质量。指纹用于输入一致性检查。报告写入异常回滚本次事务。在诊断写入失败时，可用 `archive.publication.fail_at('report_header')` 或 `archive.publication.fail_at('report_distribution')` 启用一次保存故障并检查恢复。

## 自适应批次试验

分析员还可以登记按响应调整分配的设计，保存实际路径回放并发布按停止长度条件化的精确报告。

```python
from trial.archive import TrialArchive

with TrialArchive.open('trials.db') as archive:
    design_id = archive.save_adaptive(1, 1, 6, 4, 4)
    replay = archive.replay_adaptive(design_id, [1, 1, 1, 1], 'AAAA')
    report = archive.test_adaptive(replay['id'])
    saved_replay = archive.read_adaptive_replay(replay['id'])
    saved_report = archive.read_adaptive_report(report['id'])
```

`save_adaptive(initial_a, initial_b, horizon, min_n, boundary)` 登记不可变设计并返回正整数 `design_id`，每次合法登记产生独立身份。初始球数与界值为正整数，`2 <= min_n <= horizon <= 18`，所有整数参数排除布尔值。

`replay_adaptive(design_id, responses, assignments)` 按到达顺序接收响应列表（非布尔整数 0 或 1）和分配序列（字符串或单字符列表），两序列同长。每步按当前球数比例分配：成功给本臂加球、失败给另一臂加球，分配概率在本步响应影响球数之前取得。S 从 0 开始，A 成功加 1、B 成功减 1、失败保持。从第 `min_n` 批起，首次 `abs(S) >= boundary` 即停，否则到 `horizon` 停止。合法记录必须恰好结束于首次停止时点；未达终点、停止后仍有记录或输入非法时整次拒绝，不发布任何内容。回放字典含 `id`、`design_id`、`design`、`responses`、`assignments`、逐步的 `steps`（`position`、分配前球数 `before`、实际分配的 Fraction `probability`、本步后的 `statistic`）、全部实际分配概率之积 `path_probability` 及最终 `statistic`。

`test_adaptive(replay_id)` 在尖锐零假设下固定各批次已观测响应，按反事实历史重算球数、分配概率、S 与停止资格，只计首次终结于实际长度 n 的路径（此前已终止或 n 批后仍能继续的路径都不计入），不请求 n 之后的响应。报告字典含 `id`、`replay_id`、`observed_statistic`、`stop_mass`（P(N=n)）、`joint_tail_mass`（P(N=n 且 |S|≥|S_obs|)，尾部含等号）及 `conditional_tail`（联合质量除以停止质量），三项均为 Fraction。回放向检验交接反事实历史的概率与首次终结资格，两种质量基于同一个终结事件：实际路径必然属于该事件，故 `path_probability <= joint_tail_mass <= stop_mass <= 1` 且 `conditional_tail * stop_mass == joint_tail_mass`。

`read_adaptive_replay(replay_id)` 与 `read_adaptive_report(report_id)` 按保存值返回独立副本，读取不重走路径也不重做检验。身份为正整数且排除布尔值，格式非法抛 ValueError，合法但不存在抛 KeyError。用 `replay_adaptive` 再提交一份合法记录即登记更正，可引用原设计或另一明确设计；修改输入列表或返回值、登记更正、关闭重开都不改变已保存的旧成果。每次发布沿用原子失败边界，`archive.publication.fail_at('report_header')` 可核验新报告写入后回滚，原回放和旧报告仍可读取，重试可正常产生报告。旧数据库打开时自动补齐自适应表，固定设计接口、CLI、交付包行为不变。

```sh
python3 -B -m examples.adaptive_cases
```

固定样例覆盖：上限即停止长度（质量 1、2/5、2/5）、上限放宽后恰在四批终结的只有 AAAA 与 BBBB（2/5、2/5、1）、更早停止的路径不参加本报告（1/3、1/5、3/5）、混合响应（5/12、5/12、1）以及更正后读回旧成果。`tests/test_adaptive.py` 中的 `oracle_masses` 与 `oracle_path` 提供独立的短路径核账，逐路径枚举全部反事实分配并核对停止质量、联合尾部质量与条件尾部。
