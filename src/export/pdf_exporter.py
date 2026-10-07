"""
src/export/pdf_exporter.py - Standalone Academic PDF Exporter for Chalk.
Uses PyQt6 QTextDocument + QPdfWriter to render publication-grade lecture notes
with mathematical formulas, callout boxes, and metadata directly to PDF,
without requiring Obsidian, Pandoc, or LaTeX compiler installations.
"""

import os
import re
import html
import logging
from typing import Optional
from src.ui.i18n import tr

logger = logging.getLogger("chalk.export.pdf")


def markdown_to_academic_html(markdown_text: str, title: Optional[str] = None) -> str:
    """
    Transforms markdown notes into publication-grade academic HTML styled for PDF print.
    Handles headers, lists, callout boxes (> [!theorem]), inline math, code blocks,
    and flashcard sections.
    """
    effective_title = title or tr("pdf_default_title")
    lines = markdown_text.splitlines()

    html_lines = []
    in_code_block = False
    in_list = False
    in_blockquote = False

    for line in lines:
        stripped = line.strip()

        # Code block fence
        if stripped.startswith("```"):
            if in_code_block:
                html_lines.append("</pre></div>")
                in_code_block = False
            else:
                lang = stripped[3:].strip()
                html_lines.append(f"<div class='code-block'><pre><code>")
                in_code_block = True
            continue

        if in_code_block:
            html_lines.append(html.escape(line))
            continue

        # Close list if not a list item
        if in_list and not (stripped.startswith("- ") or stripped.startswith("* ") or re.match(r"^\d+\.\s", stripped)):
            html_lines.append("</ul>")
            in_list = False

        # Close blockquote if empty line or non-quote
        if in_blockquote and not stripped.startswith(">"):
            html_lines.append("</blockquote>")
            in_blockquote = False

        if not stripped:
            html_lines.append("<p class='spacing'></p>")
            continue

        # Headers
        if stripped.startswith("# "):
            title_text = html.escape(stripped[2:])
            html_lines.append(f"<h1>{title_text}</h1>")
            continue
        elif stripped.startswith("## "):
            h2_text = html.escape(stripped[3:])
            html_lines.append(f"<h2>{h2_text}</h2>")
            continue
        elif stripped.startswith("### "):
            h3_text = html.escape(stripped[4:])
            html_lines.append(f"<h3>{h3_text}</h3>")
            continue
        elif stripped.startswith("#### "):
            h4_text = html.escape(stripped[5:])
            html_lines.append(f"<h4>{h4_text}</h4>")
            continue

        # Blockquote / Callouts (> [!theorem] Title)
        if stripped.startswith(">"):
            quote_content = stripped[1:].strip()
            callout_match = re.match(r"^\[!(theorem|definition|proof|remark|example|question|warning|note)\]\s*(.*)", quote_content, re.IGNORECASE)
            if callout_match:
                ctype = callout_match.group(1).lower()
                cheader = callout_match.group(2).strip() or ctype.capitalize()
                if not in_blockquote:
                    html_lines.append(f"<blockquote class='callout callout-{ctype}'>")
                    in_blockquote = True
                html_lines.append(f"<div class='callout-title'><b>{html.escape(cheader)}</b></div>")
                continue

            if not in_blockquote:
                html_lines.append("<blockquote>")
                in_blockquote = True
            
            # Format text inside quote
            text_escaped = _format_inline_markdown(quote_content)
            html_lines.append(f"<div>{text_escaped}</div>")
            continue

        # List items
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            item_text = _format_inline_markdown(stripped[2:])
            html_lines.append(f"<li>{item_text}</li>")
            continue

        # Regular paragraphs
        para_text = _format_inline_markdown(stripped)
        html_lines.append(f"<p>{para_text}</p>")

    if in_list:
        html_lines.append("</ul>")
    if in_blockquote:
        html_lines.append("</blockquote>")
    if in_code_block:
        html_lines.append("</pre></div>")

    body_content = "\n".join(html_lines)

    full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.55;
    color: #1E293B;
}}
h1 {{
    font-size: 19pt;
    font-weight: 700;
    color: #0F172A;
    border-bottom: 2px solid #E2E8F0;
    padding-bottom: 8px;
    margin-top: 0;
    margin-bottom: 12px;
}}
h2 {{
    font-size: 14pt;
    font-weight: 600;
    color: #1E293B;
    border-bottom: 1px solid #F1F5F9;
    padding-bottom: 4px;
    margin-top: 18px;
    margin-bottom: 8px;
}}
h3 {{
    font-size: 12pt;
    font-weight: 600;
    color: #334155;
    margin-top: 14px;
    margin-bottom: 6px;
}}
h4 {{
    font-size: 11pt;
    font-weight: 600;
    color: #475569;
    margin-top: 10px;
    margin-bottom: 4px;
}}
p {{
    margin-top: 4px;
    margin-bottom: 8px;
    text-align: justify;
}}
.spacing {{
    height: 4px;
    margin: 0;
}}
ul {{
    margin-top: 4px;
    margin-bottom: 10px;
    padding-left: 20px;
}}
li {{
    margin-bottom: 4px;
}}
blockquote {{
    border-left: 3px solid #64748B;
    margin: 10px 0;
    padding: 8px 14px;
    background-color: #F8FAFC;
    color: #334155;
}}
.callout {{
    border-left: 4px solid #3B82F6;
    background-color: #F8FAFC;
    padding: 10px 14px;
    margin: 10px 0;
}}
.callout-theorem {{
    border-left-color: #2563EB;
}}
.callout-definition {{
    border-left-color: #059669;
}}
.callout-proof {{
    border-left-color: #7C3AED;
}}
.callout-warning {{
    border-left-color: #D97706;
}}
.callout-title {{
    font-size: 10.5pt;
    margin-bottom: 4px;
    color: #0F172A;
}}
.code-block {{
    background-color: #F1F5F9;
    border: 1px solid #E2E8F0;
    padding: 8px 12px;
    margin: 10px 0;
}}
pre {{
    margin: 0;
    font-family: ui-monospace, "SFMono-Regular", Menlo, Monaco, Consolas, monospace;
    font-size: 9.5pt;
}}
code {{
    font-family: ui-monospace, "SFMono-Regular", Menlo, Monaco, Consolas, monospace;
    background-color: #F1F5F9;
    padding: 1px 4px;
    font-size: 9.5pt;
}}
.math-block {{
    font-family: "Cambria Math", "Times New Roman", Georgia, serif;
    font-size: 11pt;
    background-color: #F8FAFC;
    border: 1px solid #E2E8F0;
    padding: 8px 12px;
    margin: 8px 0;
    text-align: center;
}}
.timestamp-pill {{
    display: inline-block;
    font-family: ui-monospace, monospace;
    font-size: 8.5pt;
    font-weight: 600;
    color: #475569;
    background: #E2E8F0;
    padding: 1px 5px;
    border-radius: 4px;
}}
.footer-meta {{
    margin-top: 30px;
    padding-top: 8px;
    border-top: 1px solid #E2E8F0;
    font-size: 8.5pt;
    color: #94A3B8;
}}
</style>
</head>
<body>
{body_content}
<div class="footer-meta">
    {tr("pdf_header_exported")}
</div>
</body>
</html>
"""
    return full_html


def _format_inline_markdown(text: str) -> str:
    """Formats bold, italic, inline code, timestamp links, and display math in a line."""
    # Escape base HTML
    res = html.escape(text)

    # Display math blocks $$...$$
    res = re.sub(r"\$\$(.*?)\$\$", r"<div class='math-block'>\1</div>", res)

    # Inline math $...$
    res = re.sub(r"\$([^\$]+)\$", r"<i>\1</i>", res)

    # Bold **text**
    res = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", res)

    # Italic *text*
    res = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", res)

    # Inline code `code`
    res = re.sub(r"`([^`]+)`", r"<code>\1</code>", res)

    # Timestamp links [HH:MM:SS](chalk-audio://...)
    res = re.sub(
        r"\[([0-9:]+)\]\(chalk-audio://[^\)]+\)",
        r"<span class='timestamp-pill'>[\1]</span>",
        res,
    )

    return res


def export_notes_to_pdf(markdown_text: str, output_path: str, title: Optional[str] = None) -> bool:
    """
    Exports markdown notes directly to a vector PDF at output_path using PyQt6 QPdfWriter.
    Returns True on success, False on error.
    """
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QTextDocument, QPdfWriter, QPageSize, QPageLayout
        from PyQt6.QtCore import QMarginsF
        import sys

        # Ensure QApplication exists in the current process
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        html_content = markdown_to_academic_html(markdown_text, title=title)

        doc = QTextDocument()
        doc.setHtml(html_content)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        writer = QPdfWriter(output_path)
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setResolution(300)

        layout = QPageLayout()
        layout.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        layout.setMargins(QMarginsF(15, 15, 15, 15))  # 15mm margins
        writer.setPageLayout(layout)

        doc.print(writer)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.info("PDF exported successfully to %s (%d bytes)", output_path, os.path.getsize(output_path))
            return True
        else:
            logger.warning("PDF export wrote 0 bytes to %s", output_path)
            return False
    except Exception as e:
        logger.error("Failed to export PDF to %s: %s", output_path, e)
        return False
