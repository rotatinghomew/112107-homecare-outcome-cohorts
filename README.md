# 居家服务的问卷换版记录

调查对象是服务家庭，样本不含真实个人信息。文件使用 UTF-8，日期采用本地日历（东八区），月份用 `YYYY-MM` 表示。多选值以分号分隔。空白值表示未提供或该项未询问。

## 数据来源

- `data/roster.csv`：每期调查家庭名册；`channel` 表示登记时可用的访谈与自填渠道。
- `data/invitations.csv`：按 `issue` 记录家庭和调查月份，区分原先分配次序和实际送发次序；`design` 标明随机试填或常规收发。
- `data/replies.csv`：现场采录的答卷与收到日期。`actual_order` 是收发台登记的次序，未回收不另填答卷。
- `data/forms.csv`：各版本的题义、选项和询问范围，联络及时段为本期指标的两类障碍。
- `data/permissions.csv`：该期成对关联权限及单份使用权；登记与生效可能不同日。
- `data/corrections.csv`：收发台对原登记次序的更正，更正的是答卷出示次序而非原分配。
- `data/criteria.csv`：最少成对份数，允许的换版偏差、次序效应和未明比例上限；后三项都以比例表示。`close_at` 为六月回收期限。
- `data/capacity.csv`：下期访谈总小时、每份各版访谈分钟数及能接收通知的自填份数上限。
- `data/notices.csv`：主管已签的下期安排，每行包含签发时使用的资料截至日、两版计划份数、办理进度与公报序列口径。

## 环境及检查

使用 Python 3.11.2 标准库，无需网络或额外安装。执行 `python3 -m unittest discover -s tests -v` 检查调查资料能否按 `data-contract.json` 读取。项目当前只提供源资料和格式检查。
