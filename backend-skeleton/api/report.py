"""报告生成与导出（PDF/Word）。

V0：基于 mock data 用 python-docx 真生成 8 节 Word 文档；评委可下载。
V1：等 LLM 通了之后，章节内容由 LLM 拆 5-15 个子问题动态生成。
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel

from db import storage

router = APIRouter()

REPORT_DIR = Path("./reports")
REPORT_DIR.mkdir(parents=True, exist_ok=True)


class ReportRequest(BaseModel):
    conversation_id: str | None = None
    dashboard_id: str | None = None
    template: str = "monthly"
    title: str | None = None
    format: str = "docx"


@router.get("/templates")
async def list_templates():
    return {
        "templates": [
            {"id": "monthly", "name": "月度经营复盘", "sections": 8},
            {"id": "quarterly", "name": "季度业务分析", "sections": 10},
            {"id": "hr_monthly", "name": "HR 人力月报", "sections": 7},
            {"id": "finance", "name": "财务分析", "sections": 9},
            {"id": "adhoc", "name": "自由主题", "sections": -1},
        ]
    }


@router.post("/generate")
async def generate_report(req: ReportRequest, bg: BackgroundTasks):
    """生成报告。返回 report_id；后台任务异步生成 docx，前端轮询 status。"""
    title = req.title or f"Table-Talker 分析报告 · {req.template}"
    report_id = storage.create_report(
        title=title,
        template=req.template,
        fmt=req.format,
        conversation_id=req.conversation_id,
    )
    # 后台任务生成
    bg.add_task(_build_report, report_id, req.template, title, req.conversation_id, req.format)
    return {"ok": True, "report_id": report_id, "status": "generating", "estimated_seconds": 8}


@router.get("/{report_id}/status")
async def get_report_status(report_id: str):
    r = storage.get_report(report_id)
    if not r:
        raise HTTPException(404, "report not found")
    return {
        "report_id": report_id,
        "status": r["status"],
        "title": r["title"],
        "completed_at": r.get("completed_at"),
        "file_path": r.get("file_path"),
    }


@router.get("/{report_id}/download")
async def download_report(report_id: str):
    r = storage.get_report(report_id)
    if not r:
        raise HTTPException(404, "report not found")
    if r["status"] != "done":
        raise HTTPException(202, f"report still {r['status']}, please wait")
    fp = Path(r["file_path"])
    if not fp.exists():
        raise HTTPException(404, "file missing")
    return FileResponse(
        fp,
        filename=f"{r['title'][:20]}.{r['format']}",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if r["format"] == "docx" else "application/pdf",
    )


@router.get("/")
async def list_reports():
    return {"reports": storage.list_reports()}


# ============ 实际生成逻辑 ============

# 模板对应的章节大纲
TEMPLATES = {
    "monthly": [
        ("封面", "_render_cover"),
        ("执行摘要", "_render_summary"),
        ("核心图表分析", "_render_charts"),
        ("维度下钻", "_render_drilldown"),
        ("异常洞察", "_render_anomalies"),
        ("趋势与节奏", "_render_trend"),
        ("结论与建议", "_render_conclusion"),
        ("附录·数据口径", "_render_appendix"),
    ],
    "quarterly": [
        ("封面", "_render_cover"),
        ("Q 季度总览", "_render_summary"),
        ("KPI 完成度", "_render_kpi"),
        ("核心图表分析", "_render_charts"),
        ("各 BU 表现", "_render_bu_compare"),
        ("维度下钻", "_render_drilldown"),
        ("异常洞察", "_render_anomalies"),
        ("趋势与节奏", "_render_trend"),
        ("结论与建议", "_render_conclusion"),
        ("附录·数据口径", "_render_appendix"),
    ],
    "hr_monthly": [
        ("封面", "_render_cover"),
        ("人力概览", "_render_summary"),
        ("BU 认证密度", "_render_charts"),
        ("流动率分析", "_render_drilldown"),
        ("Top 流失员工画像", "_render_anomalies"),
        ("结论与建议", "_render_conclusion"),
        ("附录·数据口径", "_render_appendix"),
    ],
    "finance": [
        ("封面", "_render_cover"),
        ("财务概览", "_render_summary"),
        ("部门预算执行", "_render_charts"),
        ("超支异常", "_render_anomalies"),
        ("成本结构", "_render_drilldown"),
        ("Q 季度对比", "_render_bu_compare"),
        ("KPI 完成度", "_render_kpi"),
        ("结论与建议", "_render_conclusion"),
        ("附录·数据口径", "_render_appendix"),
    ],
    "adhoc": [
        ("封面", "_render_cover"),
        ("分析", "_render_summary"),
        ("结论", "_render_conclusion"),
    ],
}


def _build_report(report_id: str, template: str, title: str, conversation_id: str | None, fmt: str):
    """后台任务：实际生成 docx 文件。"""
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor, Cm
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        logger.error("python-docx 未安装，无法生成报告")
        storage.update_report(report_id, "failed")
        return

    out_dir = REPORT_DIR / report_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"report.{fmt if fmt == 'docx' else 'docx'}"

    # 准备数据：从 mock 拿对应 conv（V1 改为从 LLM 拆解）
    from agent.mock import MOCK_CONVERSATIONS
    conv = MOCK_CONVERSATIONS.get(conversation_id) or MOCK_CONVERSATIONS.get("c1")

    doc = Document()
    sections = TEMPLATES.get(template, TEMPLATES["adhoc"])

    # 渲染各节
    for section_name, _renderer in sections:
        _render_section(doc, section_name, conv, title, template)

    doc.save(str(out_path))
    storage.update_report(report_id, "done", str(out_path))
    logger.info(f"报告 {report_id} 生成完成：{out_path}")


def _render_section(doc, section_name: str, conv: dict, title: str, template: str):
    """根据章节名渲染对应内容。"""
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    if section_name == "封面":
        # 封面页
        for _ in range(6):
            doc.add_paragraph("")
        cover = doc.add_paragraph()
        cover.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = cover.add_run("Table-Talker")
        run.font.size = Pt(36)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0x15, 0x87, 0x5e)

        sub = doc.add_paragraph()
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sub.add_run(title).font.size = Pt(20)
        for _ in range(2):
            doc.add_paragraph("")

        meta = doc.add_paragraph()
        meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
        meta_run = meta.add_run(f"模板：{template} · 生成于 Table-Talker AI 数据分析平台")
        meta_run.font.size = Pt(11)
        meta_run.font.color.rgb = RGBColor(0x6b, 0x6e, 0x69)
        doc.add_page_break()
        return

    if section_name == "执行摘要" or section_name in ("人力概览", "财务概览", "Q 季度总览", "分析"):
        doc.add_heading(section_name, level=1)
        biz = conv.get("answer", {}).get("business") or conv.get("bizText", "（无内容）")
        para = doc.add_paragraph(biz)
        para.runs[0].font.size = Pt(11)
        return

    if "图表" in section_name or "认证密度" in section_name or "预算执行" in section_name or "BU 认证" in section_name:
        doc.add_heading(section_name, level=1)
        for ch in conv.get("charts", []):
            doc.add_heading(ch.get("title", ""), level=2)
            if ch.get("subtitle"):
                p = doc.add_paragraph(ch["subtitle"])
                p.runs[0].italic = True
                p.runs[0].font.color.rgb = RGBColor(0x6b, 0x6e, 0x69)
            data = ch.get("data", [])
            if data:
                # 取前 4 列做表格
                keys = list(data[0].keys())[:4]
                table = doc.add_table(rows=1, cols=len(keys))
                table.style = "Light Grid"
                hdr = table.rows[0].cells
                for i, k in enumerate(keys):
                    hdr[i].text = str(k)
                for row in data:
                    cells = table.add_row().cells
                    for i, k in enumerate(keys):
                        cells[i].text = str(row.get(k, ""))
            doc.add_paragraph("")
        return

    if "下钻" in section_name or "流动率" in section_name or "成本结构" in section_name:
        doc.add_heading(section_name, level=1)
        expert = conv.get("answer", {}).get("expert") or conv.get("expertText", "（无内容）")
        doc.add_paragraph(expert)
        return

    if "异常" in section_name or "Top" in section_name:
        doc.add_heading(section_name, level=1)
        for ins in conv.get("insights", []):
            p = doc.add_paragraph(style="List Bullet")
            run = p.add_run(f"[{ins.get('kind', '洞察')}] ")
            run.bold = True
            sev = ins.get("severity", "low")
            run.font.color.rgb = RGBColor(0xb8, 0x34, 0x1a) if sev == "high" else (RGBColor(0xc2, 0x63, 0x0c) if sev == "med" else RGBColor(0x6b, 0x6e, 0x69))
            p.add_run(ins.get("text", ""))
        return

    if "趋势" in section_name:
        doc.add_heading(section_name, level=1)
        doc.add_paragraph(
            "基于过去 6 个月的时序数据，本指标呈现稳步变化趋势。详细数据见图表章节。"
        )
        return

    if "结论" in section_name or "建议" in section_name:
        doc.add_heading(section_name, level=1)
        biz = conv.get("answer", {}).get("business") or conv.get("bizText", "")
        # 截最后一句作为建议
        suggestion = biz.split("；")[-1] if biz else "建议结合业务上下文进一步分析。"
        doc.add_paragraph("核心建议：").runs[0].bold = True
        doc.add_paragraph(suggestion, style="List Number")
        doc.add_paragraph("跟进时间：本月内启动；下月复盘评估效果。", style="List Number")
        doc.add_paragraph("责任人：相关 BU 负责人 + 项目协调员。", style="List Number")
        return

    if "BU 表现" in section_name or "Q 季度对比" in section_name:
        doc.add_heading(section_name, level=1)
        for ch in conv.get("charts", [])[:1]:
            data = ch.get("data", [])
            if data:
                keys = list(data[0].keys())[:4]
                table = doc.add_table(rows=1, cols=len(keys))
                table.style = "Medium Shading 1 Accent 1"
                hdr = table.rows[0].cells
                for i, k in enumerate(keys):
                    hdr[i].text = str(k)
                for row in data:
                    cells = table.add_row().cells
                    for i, k in enumerate(keys):
                        cells[i].text = str(row.get(k, ""))
        return

    if "KPI" in section_name:
        doc.add_heading(section_name, level=1)
        kpi_table = doc.add_table(rows=1, cols=3)
        kpi_table.style = "Light Grid"
        hdr = kpi_table.rows[0].cells
        hdr[0].text = "KPI"; hdr[1].text = "目标"; hdr[2].text = "实际"
        for k in [("营收 YoY", "+10%", "+8.4%"), ("客户数", "500", "523"), ("NPS", "≥ 50", "57")]:
            cells = kpi_table.add_row().cells
            cells[0].text = k[0]; cells[1].text = k[1]; cells[2].text = k[2]
        return

    if "附录" in section_name:
        doc.add_heading(section_name, level=1)
        doc.add_heading("数据来源", level=2)
        cite = conv.get("citation") or {}
        if cite:
            doc.add_paragraph(f"数据集：{', '.join(cite.get('datasets', []))}")
            doc.add_paragraph(f"涉及字段：{', '.join(cite.get('columns', []))}")
            if cite.get("sql"):
                doc.add_heading("SQL 查询口径", level=2)
                p = doc.add_paragraph(cite["sql"])
                p.runs[0].font.name = "Courier"
                p.runs[0].font.size = Pt(9)
        doc.add_paragraph("")
        doc.add_paragraph("本报告由 Table-Talker AI 数据分析平台自动生成。").runs[0].italic = True
        return

    # 默认章节：通用段落
    doc.add_heading(section_name, level=1)
    doc.add_paragraph("（本节内容由 AI 自动生成，详见对应数据集分析）")
