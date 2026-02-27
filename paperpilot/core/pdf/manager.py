"""
PDFManager — PDF 文件关联、指纹计算、文本提取、列表管理。

数据持久化依赖 records 表：
  - pdf_path    : 字符串，PDF 绝对路径
  - fingerprint : 字符串，sha256 hex
"""

import hashlib
import os
import shutil
import sqlite3
from pathlib import Path


class PDFManager:
    """管理项目 PDF 文件的关联与元数据。"""

    def __init__(self, project_path: str):
        """
        Parameters
        ----------
        project_path : str
            项目根目录。PDF 文件存放在 <project_path>/pdfs/。
            数据库文件为 <project_path>/paperpilot.db。
        """
        self.project_path = Path(project_path)
        self.pdf_dir = self.project_path / "pdfs"
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.project_path / "paperpilot.db"

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _update_record_fields(self, record_id: str, **fields) -> None:
        """将任意字段写入 records 表。"""
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [record_id]
        with self._get_connection() as conn:
            conn.execute(
                f"UPDATE records SET {set_clause} WHERE id = ?", values
            )

    def _get_record_field(self, record_id: str, field: str):
        """读取单个字段值，记录不存在时返回 None。"""
        with self._get_connection() as conn:
            row = conn.execute(
                f"SELECT {field} FROM records WHERE id = ?", (record_id,)
            ).fetchone()
        return row[field] if row else None

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def compute_fingerprint(self, path: str) -> str:
        """返回文件的 sha256 hex 字符串。"""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def link_pdf(
        self, record_id: str, src_path: str, copy: bool = True
    ) -> dict:
        """
        将 PDF 关联到指定记录。

        Parameters
        ----------
        record_id : str
            records 表中的记录 ID。
        src_path : str
            源 PDF 文件的绝对或相对路径。
        copy : bool
            True  → 复制到 pdfs/ 目录并重命名为 <record_id>.pdf；
            False → 仅记录原始路径，不移动文件。

        Returns
        -------
        dict
            {"pdf_path": str, "sha256": str, "page_count": int, "file_size": int}
        """
        src = Path(src_path).resolve()
        if not src.exists():
            raise FileNotFoundError(f"PDF 文件不存在: {src}")

        if copy:
            dest = self.pdf_dir / f"{record_id}.pdf"
            shutil.copy2(str(src), str(dest))
            pdf_path = str(dest)
        else:
            pdf_path = str(src)

        sha256 = self.compute_fingerprint(pdf_path)
        file_size = os.path.getsize(pdf_path)
        page_count = self._count_pages(pdf_path)

        # 持久化到数据库（字段已存在）
        try:
            self._update_record_fields(
                record_id,
                pdf_path=pdf_path,
                fingerprint=sha256,
            )
        except Exception:
            # 数据库不可用时不中断主流程
            pass

        return {
            "pdf_path": pdf_path,
            "sha256": sha256,
            "page_count": page_count,
            "file_size": file_size,
        }

    def _count_pages(self, pdf_path: str) -> int:
        """尝试用 pdfplumber 统计页数，失败时返回 -1。"""
        try:
            import pdfplumber  # type: ignore

            with pdfplumber.open(pdf_path) as pdf:
                return len(pdf.pages)
        except Exception:
            return -1

    def extract_text(self, record_id: str) -> dict:
        """
        用 pdfplumber 提取指定记录 PDF 的全文。

        Returns
        -------
        dict
            {"text": str, "pages": int, "word_count": int}

        Raises
        ------
        ImportError
            若 pdfplumber 未安装。
        FileNotFoundError
            若记录没有关联 PDF 或文件不存在。
        """
        try:
            import pdfplumber  # type: ignore
        except ModuleNotFoundError as e:
            raise ImportError(
                "pdfplumber 未安装，请执行 pip install pdfplumber"
            ) from e

        pdf_path = self.get_pdf_path(record_id)
        if pdf_path is None:
            raise FileNotFoundError(
                f"记录 {record_id!r} 没有关联 PDF 文件"
            )

        pages_text: list[str] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                pages_text.append(text)

        full_text = "\n".join(pages_text)
        word_count = len(full_text.split())

        return {
            "text": full_text,
            "pages": len(pages_text),
            "word_count": word_count,
        }

    def get_pdf_path(self, record_id: str) -> str | None:
        """
        返回记录关联的 PDF 文件路径。

        先查数据库；若数据库不可用，则检查默认路径
        ``<pdf_dir>/<record_id>.pdf``。

        Returns
        -------
        str | None
            存在则返回路径字符串，否则返回 None。
        """
        # 优先从数据库读取
        try:
            db_path = self._get_record_field(record_id, "pdf_path")
            if db_path and Path(db_path).exists():
                return db_path
        except Exception:
            pass

        # 回退到默认路径
        default = self.pdf_dir / f"{record_id}.pdf"
        if default.exists():
            return str(default)

        return None

    def list_pdfs(self) -> list[dict]:
        """
        列出所有已在数据库中登记 pdf_path 的记录。

        Returns
        -------
        list[dict]
            [{"record_id": str, "path": str, "exists": bool}, ...]
        """
        results: list[dict] = []
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT id, pdf_path FROM records WHERE pdf_path IS NOT NULL AND pdf_path != ''"
                ).fetchall()
            for row in rows:
                path = row["pdf_path"]
                results.append(
                    {
                        "record_id": row["id"],
                        "path": path,
                        "exists": Path(path).exists(),
                    }
                )
        except Exception:
            # 数据库不可用时，扫描 pdfs/ 目录作为后备
            for f in self.pdf_dir.glob("*.pdf"):
                results.append(
                    {
                        "record_id": f.stem,
                        "path": str(f),
                        "exists": True,
                    }
                )
        return results
