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

## 分析与办理流程

项目现已接入 `survey_center` 标准库包，统一处理指标分类、首份观测、授权配对、政策可比性、趋势范围、签发能力和轮次对账。

```bash
python3 -m survey_center validate
python3 -m survey_center build
python3 -m survey_center reconcile --as-of 2026-08-01
python3 -m survey_center publish-snapshot --as-of 2026-08-01
python3 -m survey_center issue --station 新桥 --group 持续照护 --mode full_new
python3 -m survey_center archive P03
python3 -m unittest discover -s tests -v
```

`python3 -m survey_center build` 会生成：

- `outputs/indicator_cells.csv`：站组指标、拒答、失访和未明分类；每户六月只取实际首版一份。
- `outputs/indicator_strata.csv`：分开两用随机试填组、两用常规组和只能访谈群体。
- `outputs/assigned_arm_evidence.csv`：按原随机分配首版列示换序、更正、失访和可见结果，避免把临时换序后的实际次序误当随机分组。
- `outputs/pair_evidence.csv`：当前有效授权下的配对率、换版偏差、实际/分配次序效应、未收到第二份数量和换序数量（仅聚合结果）。
- `outputs/comparability.csv`：按 `criteria.csv` 的最少配对数、偏差、次序效应和未明比例给出的站组判定。
- `outputs/trends.csv`、`outputs/region_scopes.csv`：原始名册基线、旧公报值、可连接范围及全区权重。
- `outputs/station_decisions.csv`、`outputs/capacity.csv`：每个站组的签发建议、暂挂份额和访谈/自填能力。
- `outputs/july_*reconciliation*.csv`：当前与 `2026-08-01` 资料截至日的七月收发对账。
- `outputs/analysis_and_dispatch.md`：中文总报告。
- `publications/`：首次发布快照；同名快照默认拒绝覆盖，以落实“后登记不回写初报”。

后续轮次可传入同结构的新收发记录：

```python
from survey_center import load_dataset, reconcile_round

ds = load_dataset("data")
result = reconcile_round(
    ds,
    month="2026-08",
    close_at="2026-08-31",
    as_of="2026-09-01",
    dispatch_rows=august_dispatches,
    receipt_rows=august_receipts,
)
```

### 必须保持的口径

1. 主指标只统计可判定为“有联络/时段障碍”或“无该类障碍”的户；整份未回、明确拒答和已答无困难分开列示。
2. 新版 `n1=否` 时不追问 `n2`；`n1=是` 但 `n2` 空白或仅“其他”时，状态为目标口径未明，不能记成无联络/时段障碍。
3. 主观测按更正后的**实际首先出示版本**选取；首份缺失、拒答或未明时，不用第二份填补。
4. 撤回关联后，该户从当前配对证据移除；若 `single_use` 仍为保留单份，首份答卷仍可单独使用。
5. 旧年报入口（`ArchiveGateway` / `archive` 子命令）只返回公报汇总，不提供成对个户答卷。
6. 只有站组级证据过门槛且全组收发渠道/能力可行时，才允许整组退原版并承诺趋势连续；部分换版只能按实际覆盖报告。
7. 全区汇总先由站组判定生成可比/不可比范围和权重，不能用全区数值反推站点合格。

## 环境及检查

使用 Python 3.11.2 标准库，无需网络或额外安装。执行 `python3 -m unittest discover -s tests -v` 可检查资料契约及上述口径。原始说明：项目最初只提供源资料和格式检查，现已加入 `survey_center` 与 `tests/test_survey_center.py`。
