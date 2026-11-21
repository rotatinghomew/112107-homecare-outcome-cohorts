# 居家服务的问卷换版记录

调查对象是服务家庭，样本不含真实个人信息。文件使用 UTF-8，日期采用本地日历（东八区），月份用 `YYYY-MM` 表示。多选值以分号分隔。空白值表示未提供或该项未询问。

## 数据来源

- `data/roster.csv`：一月和六月的调查家庭名册；`channel` 表示登记时可用的访谈与自填渠道。七月延续六月名册及渠道，发放和回收进度另记。
- `data/invitations.csv`：按 `issue` 记录家庭和调查月份，区分原先分配次序和实际送发次序；`design` 标明随机试填或常规收发。
- `data/replies.csv`：现场采录的答卷与收到日期。`actual_order` 是收发台登记的次序，未回收不另填答卷。
- `data/forms.csv`：各版本的题义、选项和询问范围，联络及时段为本期指标的两类障碍。
- `data/permissions.csv`：该期成对关联权限及单份使用权；登记与生效可能不同日。
- `data/corrections.csv`：收发台对原登记次序的更正，更正的是答卷出示次序而非原分配。
- `data/criteria.csv`：最少成对份数，允许的换版偏差、次序效应和未明比例上限；偏差与次序效应的上限为绝对百分点，用小数表示。`close_at` 为六月试填轮次回收期限。
- `data/capacity.csv`：下期访谈总小时、每份各版访谈分钟数及能接收通知的自填份数上限。
- `data/notices.csv`：主管已签的下期安排，每行包含签发时使用的资料截至日、两版计划份数、办理进度与公报序列口径。
- `data/archive_reports.csv`：已经对外发布的公报摘录。`scope` 是当时公布的统计范围，`households` 是进入该行指标的家庭数，`barrier_households` 是其中报告有联络或时段障碍的家庭数。这里保留的是历史公布值，不是用现有记录重算的结果。
- `data/july_dispatches.csv`：按发布单与家庭登记已约访谈或已发自填。未行动的计划份额未生成发放记录。`registered_at` 是工作人员能查到这次发放的日期。`receipt` 为七月回执引用。
- `data/july_receipts.csv`：引用已发给该户的 `receipt`；含登记日、实际回收日和与试填答卷相同的题项列。七月回收截止日为 7 月 31 日。未回收不另填回执。

## 环境及检查

使用 Python 3.11.2 标准库，无需网络或额外安装。执行 `python3 -m unittest discover -s tests -v` 检查调查资料能否按 `data-contract.json` 读取。项目当前只提供源资料和格式检查。
