from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
SHOWCASE = ROOT / "showcase"


def read_json(name: str) -> dict[str, Any]:
    path = REPORTS / name
    if not path.is_file():
        raise FileNotFoundError(f"缺少本機驗收來源：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def stable_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    p2b = read_json("p2b-verification.json")
    p2c = read_json("p2c-verification.json")
    p2d1 = read_json("p2d1-verification.json")
    p2d2 = read_json("p2d2-verification.json")
    p2d3 = read_json("p2d3-verification.json")

    public: dict[str, Any] = {
        "schema_version": "p2e-public-evidence-v1",
        "artifact": "MCP 工具整合與授權治理",
        "core_version": p2d3["version"],
        "showcase_version": "1.0.0",
        "verified_on": p2d3["verified_on"],
        "evidence_kind": "dated_local_synthetic_evidence",
        "live_status": "not_checked",
        "summary": {
            "profiles": 2,
            "read_tools": p2b["mcp"]["read_tools"],
            "approval_gated_write_tools": p2c["mcp"]["approval_gated_write_tools"],
            "migration_steps": p2d3["migration"]["applied"],
            "restore_zero_authority_checks": len(p2d3["restore_authority"]),
        },
        "checks": {
            "backend": p2d3["checks"]["backend_tests"],
            "frontend_component": p2d3["checks"]["frontend_component_tests"],
            "e2e": p2d3["checks"]["chrome_e2e_tests"],
            "production_build": p2d3["checks"]["production_build"],
            "desktop_and_390px_mobile": p2d3["checks"]["desktop_and_390px_mobile"],
            "privacy_allowlist_scan": p2d3["checks"]["privacy_allowlist_scan"],
        },
        "governance": {
            "single_and_dual_approval": p2c["checks"]["single_and_dual_approval"],
            "self_review_blocked": p2c["checks"]["self_review_blocked"],
            "admin_bypass_blocked": p2c["checks"]["admin_bypass_blocked"],
            "parallel_exactly_one_order": p2c["checks"]["parallel_exactly_one_order"],
            "lost_response_recovered_without_duplicate": p2c["checks"]["lost_response_recovered_without_duplicate"],
            "account_lifecycle": "passed_local",
            "profile_version_workflow": "passed_local",
        },
        "migration": {
            "schema": p2d3["migration"]["schema"],
            "applied": p2d3["migration"]["applied"],
            "pending": p2d3["migration"]["pending"],
            "checksum_drift": p2d3["migration"]["checksum_drift"],
        },
        "restore_authority": p2d3["restore_authority"],
        "milestones": [
            {"id": "P2-B", "version": p2b["product_version"], "status": p2b["status"]},
            {"id": "P2-C", "version": p2c["product_version"], "status": p2c["status"]},
            {"id": "P2-D-1", "version": p2d1["version"], "status": p2d1["result"]},
            {"id": "P2-D-2", "version": p2d2["version"], "status": p2d2["result"]},
            {"id": "P2-D-3", "version": p2d3["version"], "status": p2d3["result"]},
        ],
        "data_notice": "所有業務資料皆為原創合成資料；本摘要是有日期的本機歷史證據，不是即時產品監控。",
        "not_claimed": [
            "真實企業資料或帳號",
            "外部工單整合",
            "即時設備控制",
            "雲端或正式生產部署",
            "跨機災難復原",
            "不可變外部稽核儲存",
        ],
    }

    payload = stable_json(public)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    public["public_payload_sha256"] = digest
    final_payload = stable_json(public)

    json_targets = [
        SHOWCASE / "src" / "evidence-summary.json",
        SHOWCASE / "public" / "data" / "evidence-summary.json",
        SHOWCASE / "public" / "downloads" / "evidence-summary.json",
    ]
    for target in json_targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(final_payload, encoding="utf-8")

    checks = public["checks"]
    markdown = f"""# MCP 工具治理｜公開證據摘要

- 核心版本：{public['core_version']}
- 介紹網站版本：{public['showcase_version']}
- 驗收日期：{public['verified_on']}
- 證據類型：有日期的本機合成資料歷史證據，非即時監控

## 已驗收範圍

- 兩組客製化 Profile
- 3 個唯讀工具＋1 個核準後寫入工具
- 單／雙人核準、自審與管理者繞過阻擋
- 並行重送只建立一張工單；結果不明可查核恢復
- 4 段 migration ledger，0 pending、0 checksum drift
- 隔離還原的 Session、授權上下文、有效核準、自動重放與 MCP 呼叫均為 0

## 0.5.0 歷史驗收分母

- 後端：{checks['backend']['passed']}/{checks['backend']['passed'] + checks['backend']['failed']}
- 前端元件：{checks['frontend_component']['passed']}/{checks['frontend_component']['passed'] + checks['frontend_component']['failed']}
- Chrome E2E：{checks['e2e']['passed']}/{checks['e2e']['passed'] + checks['e2e']['failed']}
- 正式建置：{checks['production_build']}
- 桌機與 390px 手機：{checks['desktop_and_390px_mobile']}
- 隱私白名單掃描：{checks['privacy_allowlist_scan']}

## 限制

{chr(10).join(f'- {item}' for item in public['not_claimed'])}

資料聲明：{public['data_notice']}
"""
    (SHOWCASE / "public" / "downloads" / "作品證據摘要.md").write_text(markdown, encoding="utf-8")
    print(f"generated {len(json_targets) + 1} public files; source hash {digest}")


if __name__ == "__main__":
    main()
