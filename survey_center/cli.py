from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .io import DEFAULT_DATA, load_dataset
from .reports import build_outputs, publish_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m survey_center",
        description="居家服务问卷换版的指标、配对、签发与收发对账工具",
    )
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="CSV 数据目录")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="读取 data-contract.json 中列出的全部表")

    archive = sub.add_parser("archive", help="查阅旧年报汇总；不提供成对个户答卷")
    archive.add_argument("report", nargs="?", default=None, help="公报编号，例如 P03；省略则列出全部")

    build = sub.add_parser("build", help="生成 outputs/ 下的分析表和 Markdown 报告")
    build.add_argument("--out", default="outputs")

    issue = sub.add_parser("issue", help="校验并签发一个站组的下期安排")
    issue.add_argument("--station", required=True)
    issue.add_argument("--group", required=True)
    issue.add_argument("--mode", default="auto",
                       choices=["auto", "full_new", "original_coverable", "dual_track", "restart_new"])
    issue.add_argument("--out", default=None, help="提供目录时写入不可覆盖的 JSON 签发单")

    reconcile = sub.add_parser("reconcile", help="输出某一资料截至日的七月对账 JSON/CSV")
    reconcile.add_argument("--as-of", default=None, help="YYYY-MM-DD；省略表示当前全部已登记记录")
    reconcile.add_argument("--out", default=None, help="可选 CSV 输出路径前缀")

    publish = sub.add_parser("publish-snapshot", help="写入不可回写的首次发布快照")
    publish.add_argument("--as-of", default="2026-08-01")
    publish.add_argument("--out", default="publications")
    publish.add_argument("--force", action="store_true", help="仅在明确需要重建测试快照时覆盖")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ds = load_dataset(args.data)

    if args.command == "validate":
        for name in ds.contract["files"]:
            expected = ds.contract["files"][name]["row_count"]
            actual = len(ds.table(name))
            if actual != expected:
                raise SystemExit(f"{name}: 期望 {expected} 行，实际 {actual} 行")
        print(f"已读取并核对 {len(ds.contract['files'])} 个数据源。")
        return 0

    if args.command == "archive":
        from .archive import ArchiveGateway

        gateway = ArchiveGateway(ds)
        if args.report:
            row = gateway.get_report(args.report)
            for key, value in row.items():
                print(f"{key}: {value}")
        else:
            for row in gateway.list_reports():
                print(f"{row['report']} {row['period']} {row['station']}{row['group']} {row['households']}户")
        print("隐私限制：旧年报入口不提供成对个户答卷。")
        return 0

    if args.command == "issue":
        from .issuance import IssuanceError, draft_arrangement, write_arrangement

        try:
            arrangement = draft_arrangement(ds, args.station, args.group, args.mode)
        except IssuanceError as exc:
            raise SystemExit(f"拒绝签发：{exc}") from exc
        print(arrangement)
        if args.out:
            path = write_arrangement(arrangement, args.out)
            print(f"已签发：{path}")
        return 0

    if args.command == "build":
        outputs = build_outputs(ds, args.out)
        print(f"已生成 {len(outputs)} 个文件到 {Path(args.out).resolve()}")
        for key, path in outputs.items():
            print(f"- {key}: {path}")
        return 0

    if args.command == "reconcile":
        from .operations import reconcile_round

        result = reconcile_round(ds, as_of=args.as_of)
        print(f"截至日：{args.as_of or '当前'}；明细 {len(result.details)} 行；发布单 {len(result.notices)} 行")
        for row in result.notices:
            print(
                f"{row['notice']} {row['station']}{row['group']}: "
                f"发放 {row['actual_dispatches']}, 有效 {row['valid_indicator_households']}, "
                f"未回 {row['no_visible_receipt']}, 拒答 {row['explicit_refusal']}, "
                f"未明 {row['caliber_unusable']}, 逾期 {row['late_processing_only']}"
            )
        if args.out:
            from .io import write_csv

            out = Path(args.out)
            write_csv(out.with_name(out.name + "_notices.csv"), result.notices)
            write_csv(out.with_name(out.name + "_details.csv"), result.details)
        return 0

    if args.command == "publish-snapshot":
        paths = publish_snapshot(ds, args.as_of, args.out, overwrite=args.force)
        for key, path in paths.items():
            print(f"已写入 {key}: {path}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
