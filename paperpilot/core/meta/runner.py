"""
paperpilot/core/meta/runner.py
MetaRunner: spawn Rscript to execute metafor-based meta-analyses.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path


class MetaRunner:
    """
    Thin Python wrapper around Rscript + metafor.

    Usage::

        runner = MetaRunner()
        if not runner.is_r_available():
            raise RuntimeError("Rscript not found. Please install R.")

        result = runner.run_random_effects(data, method="REML")
    """

    def __init__(self, r_executable: str = "Rscript") -> None:
        self._r = r_executable

    # ── Public API ────────────────────────────────────────────────────────

    def is_r_available(self) -> bool:
        """检测 R (Rscript) 是否已安装并可执行。"""
        try:
            result = subprocess.run(
                [self._r, "--version"],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    def run_random_effects(
        self,
        data: list[dict],
        method: str = "REML",
    ) -> dict:
        """
        运行随机效应模型（metafor::rma）。

        参数:
            data:   [{"yi": float, "vi": float, ...}, ...]
            method: REML | DL | HE | HS | PM

        返回:
            {
              "estimate": float,
              "se": float,
              "ci_lower": float,
              "ci_upper": float,
              "I2": float,
              "tau2": float,
              "Q": float,
              "Q_pval": float,
              "k": int,
              "method": str,
            }

        异常:
            ValueError  — 数据不足或字段缺失
            RuntimeError — R 执行失败
        """
        if not data:
            raise ValueError("data must not be empty.")
        if len(data) < 2:
            raise ValueError(
                f"At least 2 studies are required for meta-analysis; got {len(data)}."
            )

        r_script = self._build_r_script(data, method)
        return self._run_r_script(r_script)

    def run_subgroup(
        self,
        data: list[dict],
        group_field: str = "group",
        method: str = "REML",
    ) -> dict[str, dict]:
        """
        按 group 分组，对每组独立运行 run_random_effects。

        参数:
            data:        含 group 键的数据列表
            group_field: 分组键名（默认 "group"）
            method:      heterogeneity 估计方法

        返回:
            {group_name: result_dict}
        """
        groups: dict[str, list[dict]] = defaultdict(list)
        for item in data:
            group_value = item.get(group_field) or "__ungrouped__"
            groups[str(group_value)].append(item)

        results: dict[str, dict] = {}
        for group_name, group_data in groups.items():
            try:
                results[group_name] = self.run_random_effects(
                    group_data, method=method
                )
            except (ValueError, RuntimeError) as exc:
                results[group_name] = {
                    "error": str(exc),
                    "group": group_name,
                    "k": len(group_data),
                }
        return results

    # ── Internal helpers ──────────────────────────────────────────────────

    def _build_r_script(self, data: list[dict], method: str) -> str:
        """
        生成 R 脚本字符串。
        metafor::rma 的结果以 JSON 格式 cat() 到 stdout。
        """
        yi_values = ", ".join(str(float(d["yi"])) for d in data)
        vi_values = ", ".join(str(float(d["vi"])) for d in data)

        script = (
            "library(metafor)\n"
            "library(jsonlite)\n"
            "dat <- data.frame(\n"
            f"  yi = c({yi_values}),\n"
            f"  vi = c({vi_values})\n"
            ")\n"
            f'res <- rma(yi, vi, data=dat, method="{method}")\n'
            "out <- list(\n"
            "  estimate = as.numeric(res$b),\n"
            "  se = as.numeric(res$se),\n"
            "  ci_lower = as.numeric(res$ci.lb),\n"
            "  ci_upper = as.numeric(res$ci.ub),\n"
            "  I2 = as.numeric(res$I2),\n"
            "  tau2 = as.numeric(res$tau2),\n"
            "  Q = as.numeric(res$QE),\n"
            "  Q_pval = as.numeric(res$QEp),\n"
            "  k = res$k,\n"
            f'  method = "{method}"\n'
            ")\n"
            "cat(toJSON(out, auto_unbox=TRUE))\n"
        )
        return script

    def _run_r_script(self, script: str) -> dict:
        """
        将 R 脚本写入临时文件，调用 Rscript 执行，解析 stdout JSON。

        异常:
            RuntimeError — Rscript 返回非零退出码或 JSON 解析失败
        """
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".R",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(script)
            tmp_path = tmp.name

        try:
            result = subprocess.run(
                [self._r, "--no-save", "--no-restore", tmp_path],
                capture_output=True,
                text=True,
                timeout=120,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if result.returncode != 0:
            stderr_snippet = (result.stderr or "")[:1000]
            raise RuntimeError(
                f"Rscript exited with code {result.returncode}.\n"
                f"stderr:\n{stderr_snippet}"
            )

        stdout = (result.stdout or "").strip()
        if not stdout:
            raise RuntimeError(
                "Rscript produced no output. "
                f"stderr:\n{(result.stderr or '')[:1000]}"
            )

        try:
            parsed: dict = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Failed to parse Rscript JSON output: {exc}\n"
                f"Raw stdout:\n{stdout[:500]}"
            ) from exc

        return parsed
