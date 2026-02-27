"""
paperpilot/core/meta/data_prep.py
Prepare and validate meta-analysis data from extracted study values.
"""

from __future__ import annotations


def prepare_meta_data(
    extracted_values: dict[str, list[dict]],
    outcome_field: str,
    se_field: str | None = None,
    n_field: str | None = None,
    group_field: str | None = None,
) -> dict:
    """
    准备 meta 分析数据。

    参数:
        extracted_values: record_id -> list of extracted value dicts
        outcome_field:    效应量字段名（yi）
        se_field:         标准误字段名（可选，vi = se^2）
        n_field:          样本量字段名（可选）
        group_field:      分组字段名（用于亚组分析，可选）

    返回:
        {
          "data": [{"record_id": str, "yi": float, "vi": float,
                    "ni": int|None, "group": str|None}],
          "n_valid": int,
          "n_missing": int,
          "errors": [str],
        }
    """
    data: list[dict] = []
    errors: list[str] = []
    n_missing = 0

    for record_id, value_list in extracted_values.items():
        if not value_list:
            n_missing += 1
            errors.append(f"Record '{record_id}': no extracted values found.")
            continue

        # Use the first entry in the list for this record
        entry = value_list[0] if isinstance(value_list, list) else value_list

        # ── Effect size (yi) ─────────────────────────────────────────────
        raw_yi = entry.get(outcome_field)
        if raw_yi is None:
            n_missing += 1
            errors.append(
                f"Record '{record_id}': missing outcome field '{outcome_field}'."
            )
            continue

        try:
            yi = float(raw_yi)
        except (TypeError, ValueError):
            n_missing += 1
            errors.append(
                f"Record '{record_id}': cannot convert yi value '{raw_yi}' to float."
            )
            continue

        # ── Variance (vi) ────────────────────────────────────────────────
        vi: float | None = None
        if se_field is not None:
            raw_se = entry.get(se_field)
            if raw_se is not None:
                try:
                    se = float(raw_se)
                    vi = se ** 2
                except (TypeError, ValueError):
                    errors.append(
                        f"Record '{record_id}': cannot convert se value '{raw_se}' to float; "
                        "vi will be None."
                    )

        if vi is None:
            # Fall back: look for a 'vi' or 'variance' key in the entry itself
            for fallback_key in ("vi", "variance", "var"):
                raw_vi = entry.get(fallback_key)
                if raw_vi is not None:
                    try:
                        vi = float(raw_vi)
                        break
                    except (TypeError, ValueError):
                        errors.append(
                            f"Record '{record_id}': cannot convert vi value "
                            f"'{raw_vi}' to float."
                        )

        if vi is None:
            n_missing += 1
            errors.append(
                f"Record '{record_id}': variance (vi) could not be determined. "
                "Provide 'se_field' or a 'vi'/'variance' key."
            )
            continue

        # ── Sample size (ni) ─────────────────────────────────────────────
        ni: int | None = None
        if n_field is not None:
            raw_n = entry.get(n_field)
            if raw_n is not None:
                try:
                    ni = int(float(raw_n))
                except (TypeError, ValueError):
                    errors.append(
                        f"Record '{record_id}': cannot convert ni value '{raw_n}' to int."
                    )

        # ── Group ────────────────────────────────────────────────────────
        group: str | None = None
        if group_field is not None:
            raw_group = entry.get(group_field)
            if raw_group is not None:
                group = str(raw_group)

        data.append(
            {
                "record_id": record_id,
                "yi": yi,
                "vi": vi,
                "ni": ni,
                "group": group,
            }
        )

    return {
        "data": data,
        "n_valid": len(data),
        "n_missing": n_missing,
        "errors": errors,
    }


def validate_meta_data(data: list[dict]) -> tuple[bool, list[str]]:
    """
    验证数据完整性。

    规则:
        - yi（效应量）必须存在且为数值
        - vi（方差）必须存在且为正数
        - 至少 3 条有效数据

    参数:
        data: prepare_meta_data 返回的 "data" 列表

    返回:
        (is_valid, error_messages)
    """
    errors: list[str] = []
    valid_count = 0

    for item in data:
        record_id = item.get("record_id", "<unknown>")
        yi = item.get("yi")
        vi = item.get("vi")

        # Check yi
        if yi is None:
            errors.append(f"Record '{record_id}': yi is missing.")
            continue
        try:
            yi_f = float(yi)
        except (TypeError, ValueError):
            errors.append(f"Record '{record_id}': yi='{yi}' is not a valid number.")
            continue

        # Check vi
        if vi is None:
            errors.append(f"Record '{record_id}': vi is missing.")
            continue
        try:
            vi_f = float(vi)
        except (TypeError, ValueError):
            errors.append(f"Record '{record_id}': vi='{vi}' is not a valid number.")
            continue

        if vi_f <= 0:
            errors.append(
                f"Record '{record_id}': vi={vi_f} must be > 0 (positive variance required)."
            )
            continue

        # All checks passed for this record
        _ = yi_f  # used to confirm conversion
        valid_count += 1

    if valid_count < 3:
        errors.append(
            f"Insufficient data: {valid_count} valid record(s) found, "
            "at least 3 are required for meta-analysis."
        )

    is_valid = (valid_count >= 3) and not any(
        "is missing" in e or "not a valid" in e or "must be > 0" in e
        for e in errors
    )

    return is_valid, errors
