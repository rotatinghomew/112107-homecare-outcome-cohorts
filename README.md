# 居家照护服务方案的分层效果跟踪

以下资料为合成记录，不含实际个人信息。文件以 UTF-8 编码，普通字段含日期或本地时间（东八区），分号表示同一字段的多值。空值表示在该记录中未提供，不自动当零。表内的凭据编号用于核对记录归属。

## 数据来源

- `data/strata.csv`：人日成本单位为小时；比例用小数，分层键取三个业务字段的组合。
- `data/audit_budget.csv`：原批分期可用人时，预留给临期联络的部分不得用于普通抽取；名单标志确定临期对象。
- `data/audit_order_log.csv`：已签发的外勤指令和抽签依据，evidence_kind 区分业务优先与概率抽核。
- `data/previous_draw.csv`：历史在样资格人数、抽核数及抽签凭证，抽签时名单通过冻结日期关联。
- `data/audits.csv`：firsthand 与 secondhand 保持不同证据依据；adjudication 由值班负责人签发。
- `data/remedial_service.csv`：原先服务周期结束后发生的实际补办，修订用于核对再次办理状态。
- `data/releases.csv`：已经签发的结论使用的日期及渠道。
- `data/roster.csv`：原始转介包含同一家庭的重复登记。以 person 和 wave 区分统计对象；due_at 是原服务约定期限。
- `data/original_contacts.csv`：常规凭据仅报告原期限内的结果，unknown 表示不能凭常规凭据确定。

## 环境及检查

使用 Python 3.11.2 标准库，无需网络或额外安装。在项目目录可执行 `python3 -m unittest discover -s tests -v` 核对输入文件、表头与记录形状。各来源字段及记录数量见 `data-contract.json`。目前提供资料读取检查，不生成业务分析结果。
