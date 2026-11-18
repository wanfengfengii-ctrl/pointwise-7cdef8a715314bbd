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
