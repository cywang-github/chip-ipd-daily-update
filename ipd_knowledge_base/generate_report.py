"""IPD 知识库综合报告生成器（单 HTML 多 Tab + 微信推送）

支持两种模式：
1. 完整五步模式：--step2 "步骤二内容" --step3 "步骤三内容" --step4 "步骤四内容"
   生成单 HTML（5 个 Tab）报告 + 推送微信（含主页内容 + 来源链接）
2. 存量扫描模式（默认）：扫描知识库 .md 文件，生成单页面综合报告

输出：
    output/index.html  — 最终报告（单 HTML 多 Tab）
    output/push_log.txt — 微信推送记录（时间 + 标题）

用法:
    python generate_report.py --step2 "..." --step3 "..." --step4 "..."
    python generate_report.py              # 存量扫描
    python generate_report.py --no-push    # 仅生成报告不推送
"""

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

SCRIPT_DIR = Path(__file__).resolve().parent
KNOWLEDGE_BASE = SCRIPT_DIR
OUTPUT_DIR = SCRIPT_DIR / "output"
PUSHPLUS_CONFIG = SCRIPT_DIR.parent.parent / "芯片导出工具" / "pushplus_config.json"
PUSHPLUS_URL = "https://www.pushplus.plus/send"

# ============================================================
# CSS 样式（单 HTML 多 Tab）
# ============================================================

CSS_STYLE = """    :root {
      --bg: #f5f5f5; --card: #fff; --text: #1a1a2e; --muted: #6b7280;
      --border: #e5e7eb; --accent: #2563eb; --accent-light: #eff6ff;
      --red: #dc2626; --red-light: #fef2f2; --amber: #d97706; --amber-light: #fffbeb;
      --green: #059669; --green-light: #ecfdf5;
      --radius: 8px; --shadow: 0 1px 2px rgba(0,0,0,.04);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: var(--bg); color: var(--text); line-height: 1.65; font-size: 14px;
    }
    .topbar {
      background: #0f172a; color: #fff; padding: 12px 24px;
      display: flex; align-items: center; justify-content: space-between;
      position: sticky; top: 0; z-index: 100;
    }
    .topbar .brand { font-weight: 700; font-size: 16px; }
    .topbar .brand span { opacity: .6; font-weight: 400; font-size: 13px; margin-left: 8px; }

    .tab-nav {
      display: flex; gap: 0; background: #fff; border-bottom: 2px solid var(--border);
      padding: 0 24px; position: sticky; top: 48px; z-index: 99;
    }
    .tab-nav button {
      padding: 14px 24px; border: none; background: none; cursor: pointer;
      font-size: 14px; font-weight: 600; color: var(--muted);
      border-bottom: 3px solid transparent; margin-bottom: -2px;
      transition: all .15s; font-family: inherit;
    }
    .tab-nav button:hover { color: var(--text); }
    .tab-nav button.active { color: var(--accent); border-bottom-color: var(--accent); }

    .tab-content { display: none; padding: 32px 40px; max-width: 1000px; margin: 0 auto; }
    .tab-content.active { display: block; }

    .hero-card {
      background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0f172a 100%);
      color: #fff; padding: 40px; border-radius: 12px; margin-bottom: 32px;
    }
    .hero-card h1 { font-size: 28px; font-weight: 700; margin-bottom: 6px; }
    .hero-card .sub { font-size: 14px; opacity: .65; }

    .metric-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 32px; }
    .metric-card {
      background: #fff; border-radius: var(--radius); padding: 20px; text-align: center;
      box-shadow: var(--shadow); border-top: 3px solid var(--accent);
    }
    .metric-card.warn { border-top-color: var(--amber); }
    .metric-card.good { border-top-color: var(--green); }
    .metric-card .num { font-size: 28px; font-weight: 800; color: var(--text); }
    .metric-card .lbl { font-size: 12px; color: var(--muted); margin-top: 4px; }

    .section-block { margin-bottom: 32px; }
    .section-block h2 {
      font-size: 18px; font-weight: 700; margin-bottom: 16px; padding-bottom: 8px;
      border-bottom: 2px solid var(--accent); display: flex; align-items: center; gap: 8px;
    }
    .section-block h2 .cnt { font-size: 13px; color: var(--muted); font-weight: 400; }

    .insight-block {
      background: var(--accent-light); border-left: 4px solid var(--accent);
      padding: 16px 20px; border-radius: 0 var(--radius) var(--radius) 0;
      margin-bottom: 16px; font-size: 13px; line-height: 1.7;
    }
    .insight-block h4 { font-size: 14px; margin-bottom: 6px; color: var(--accent); }

    /* 检索源卡片网格 */
    .source-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 24px; }
    .source-card {
      background: #fff; border-radius: var(--radius); padding: 20px; box-shadow: var(--shadow);
      border-left: 3px solid var(--accent);
    }
    .source-card.cat-a { border-left-color: #6366f1; }
    .source-card.cat-b { border-left-color: #f59e0b; }
    .source-card.cat-c { border-left-color: #10b981; }
    .source-card.cat-d { border-left-color: #8b5cf6; }
    .source-card.cat-e { border-left-color: #ef4444; }
    .source-card.cat-f { border-left-color: #6b7280; }
    .source-card .cat-label {
      font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em;
      margin-bottom: 6px;
    }
    .source-card.cat-a .cat-label { color: #6366f1; }
    .source-card.cat-b .cat-label { color: #f59e0b; }
    .source-card.cat-c .cat-label { color: #10b981; }
    .source-card.cat-d .cat-label { color: #8b5cf6; }
    .source-card.cat-e .cat-label { color: #ef4444; }
    .source-card.cat-f .cat-label { color: #6b7280; }
    .source-card p { font-size: 13px; color: #374151; margin-bottom: 6px; line-height: 1.55; }
    .source-card .src-link {
      display: inline-flex; align-items: center; gap: 4px; margin-top: 8px;
      font-size: 12px; color: var(--accent); text-decoration: none; font-weight: 600;
    }
    .source-card .src-link:hover { text-decoration: underline; }
    .source-card .tag-row { margin-top: 6px; display: flex; gap: 4px; flex-wrap: wrap; }

    .tag { display: inline-block; padding: 1px 8px; border-radius: 100px; font-size: 11px; font-weight: 600; }
    .tag-ref { background: var(--accent-light); color: var(--accent); }
    .tag-risk { background: var(--red-light); color: var(--red); }
    .tag-ok { background: var(--green-light); color: var(--green); }
    .tag-warn { background: var(--amber-light); color: var(--amber); }
    .tag-new { background: #f0fdf4; color: #166534; }

    .rec-card {
      background: #fff; border-radius: var(--radius); padding: 20px; box-shadow: var(--shadow);
      margin-bottom: 12px; border-left: 4px solid var(--accent);
    }
    .rec-card.p0 { border-left-color: var(--red); }
    .rec-card.p1 { border-left-color: var(--amber); }
    .rec-card.p2 { border-left-color: var(--green); }
    .rec-card .pri {
      font-size: 11px; font-weight: 700; letter-spacing: .04em; margin-bottom: 4px;
    }
    .rec-card.p0 .pri { color: var(--red); }
    .rec-card.p1 .pri { color: var(--amber); }
    .rec-card.p2 .pri { color: var(--green); }
    .rec-card h4 { font-size: 15px; margin-bottom: 6px; }
    .rec-card p { font-size: 13px; color: #374151; line-height: 1.6; }
    .rec-card .ref-link { font-size: 12px; color: var(--accent); margin-top: 6px; }
    .rec-card .ref-link a { color: var(--accent); }

    .full-card {
      background: #fff; border-radius: var(--radius); padding: 28px; box-shadow: var(--shadow);
      margin-bottom: 16px;
    }
    .full-card h3 { font-size: 17px; margin-bottom: 14px; color: #111827; }
    .full-card h4 { font-size: 14px; margin: 20px 0 8px; color: #374151; }
    .full-card p, .full-card li { margin-bottom: 8px; font-size: 14px; line-height: 1.65; }
    .full-card ul, .full-card ol { margin-left: 22px; margin-bottom: 12px; }

    .gap-table { width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 24px; }
    .gap-table th { background: #f1f5f9; padding: 10px 14px; text-align: left; font-size: 12px;
      font-weight: 600; color: #374151; text-transform: uppercase; letter-spacing: .04em; }
    .gap-table td { padding: 10px 14px; border-bottom: 1px solid var(--border); }

    .footer {
      text-align: center; font-size: 12px; color: var(--muted);
      padding: 24px 40px; border-top: 1px solid var(--border); margin-top: 32px;
    }

    @media (max-width: 900px) {
      .tab-nav { overflow-x: auto; }
      .tab-nav button { padding: 14px 16px; white-space: nowrap; }
      .tab-content { padding: 24px 16px; }
      .metric-row { grid-template-columns: repeat(3, 1fr); }
      .source-grid { grid-template-columns: 1fr; }
    }"""

# ============================================================
# 检索源分类定义
# ============================================================

CATEGORY_INFO = {
    "A": {"name": "国外公司", "css_class": "cat-a", "icon": "🌐"},
    "B": {"name": "国内公司", "css_class": "cat-b", "icon": "🇨🇳"},
    "C": {"name": "GitHub 项目", "css_class": "cat-c", "icon": "📦"},
    "D": {"name": "学术论文", "css_class": "cat-d", "icon": "📄"},
    "E": {"name": "行业标准", "css_class": "cat-e", "icon": "📋"},
    "F": {"name": "待补充方向", "css_class": "cat-f", "icon": "🔍"},
}


class SourceItem(NamedTuple):
    """检索源条目"""
    category: str          # A/B/C/D/E/F
    title: str             # 条目标题
    content: str           # 核心内容（不含日期）
    source_url: str        # 来源链接
    tags: list[str]        # 标签：new/ref/risk/warn


def extract_urls(text: str) -> list[str]:
    """从文本中提取所有 URL"""
    urls = re.findall(r'https?://[^\s<>"\']+', text)
    # 清理尾部标点
    cleaned = []
    for u in urls:
        u = u.rstrip('.,;:!?)」】）')
        cleaned.append(u)
    return cleaned


def strip_date(text: str) -> str:
    """移除文本中的日期信息"""
    # 匹配多种日期格式
    text = re.sub(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?', '', text)
    text = re.sub(r'\d{4}-\d{2}-\d{2}', '', text)
    text = re.sub(r'\b(20\d{2})年\d{1,2}月\d{1,2}日\b', '', text)
    text = re.sub(r'（\d{4}-\d{2}-\d{2}）', '', text)
    text = re.sub(r'\(\d{4}-\d{2}-\d{2}\)', '', text)
    # 清理多余空格
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def load_source_url_map() -> dict[str, str]:
    """从检索源清单中加载来源名称→URL 的映射"""
    source_file = KNOWLEDGE_BASE / "检索源清单.md"
    if not source_file.exists():
        return {}
    text = source_file.read_text(encoding="utf-8")
    url_map: dict[str, str] = {}

    # 匹配 Markdown 链接: [文本](URL)
    for match in re.finditer(r'\[([^\]]+)\]\((https?://[^)]+)\)', text):
        label = match.group(1).strip()
        url = match.group(2).strip()
        url_map[label] = url

    # 匹配裸 URL 旁边的描述文本
    for match in re.finditer(r'(https?://[^\s<>"\']+)', text):
        url = match.group(1).rstrip('.,;:!?)」】）')
        # 尝试从前面的文本中提取描述
        before = text[max(0, match.start() - 100):match.start()]
        desc_match = re.search(r'[（(]([^）)]+)[）)]\s*$', before)
        if desc_match:
            url_map[desc_match.group(1).strip()] = url

    # 添加常用来源映射
    url_map.update({
        "EE Times": "https://www.eetimes.com/",
        "EE Times Taiwan": "https://www.eettaiwan.com/",
        "Semiconductor Engineering": "https://semiengineering.com/",
        "EET-CHINA": "https://www.eet-china.com/",
        "EET-China": "https://www.eet-china.com/",
        "CSDN": "https://www.csdn.net/",
        "ONES Blog": "https://ones.ai/blog",
        "TCGen": "https://www.tcgen.com/blog",
        "CIMdata": "https://www.cimdata.com/",
        "McKinsey": "https://www.mckinsey.com/industries/semiconductors",
        "EETOP": "https://www.eetop.cn/",
        "Hot Chips": "https://www.hotchips.org/",
        "ISSCC": "https://www.isscc.org/",
        "DAC": "https://www.dac.com/",
        "SEMICON": "https://www.semi.org/",
        "SEMICON China": "https://www.semiconchina.org/",
        "ISPD": "https://www.ispd.cc/",
        "GitHub": "https://github.com/",
        "Semantic Scholar": "https://www.semanticscholar.org/",
        "arXiv": "https://arxiv.org/",
        "IEEE": "https://ieeexplore.ieee.org/",
        "AEC Council": "https://www.aecouncil.com/",
        "ISO": "https://www.iso.org/",
        "Siemens": "https://www.plm.automation.siemens.com/",
        "Perforce": "https://www.perforce.com/",
        "TSMC": "https://www.tsmc.com/",
        "TSMC OIP": "https://www.tsmc.com/english/dedicatedFoundry/oip",
        "Cadence": "https://www.cadence.com/",
        "Synopsys": "https://www.synopsys.com/",
        "禅道": "https://www.zentao.net/",
        "禅道项目管理": "https://www.zentao.net/",
        "飞书项目": "https://www.feishu.cn/",
        "SegmentFault": "https://segmentfault.com/",
        "华为云社区": "https://bbs.huaweicloud.com/",
        "163.com": "https://www.163.com/",
        "Woodside Capital": "https://woodsidecap.com/",
        "Woodside Capital Partners": "https://woodsidecap.com/",
        "All About Circuits": "https://www.allaboutcircuits.com/",
        "Electrek": "https://electrek.co/",
        "WCCFTech": "https://wccftech.com/",
        "Business Korea": "https://www.businesskorea.co.kr/",
        "nexuspi": "https://nexuspi.com/",
        "blog.gitcode.com": "https://blog.gitcode.com/",
        "Tesla": "https://www.tesla.com/",
        "NVIDIA": "https://www.nvidia.com/",
        "AMD": "https://www.amd.com/",
        "Intel": "https://www.intel.com/",
        "Apple": "https://www.apple.com/",
        "STMicro": "https://www.st.com/",
        "STMicroelectronics": "https://www.st.com/",
        "NXP": "https://www.nxp.com/",
        "Infineon": "https://www.infineon.com/",
        "TI": "https://www.ti.com/",
        "Qualcomm": "https://www.qualcomm.com/",
        "Broadcom": "https://www.broadcom.com/",
        "Renesas": "https://www.renesas.com/",
        "ADI": "https://www.analog.com/",
        "华为": "https://www.huawei.com/",
        "海思": "https://www.hisilicon.com/",
        "比亚迪": "https://www.byd.com/",
        "比亚迪半导体": "https://www.byd.com/",
        "紫光展锐": "https://www.unisoc.com/",
        "韦尔半导体": "https://www.willsemi.com/",
        "卓胜微": "https://www.maxscend.com/",
        "寒武纪": "https://www.cambricon.com/",
        "地平线": "https://www.horizon.ai/",
        "黑芝麻智能": "https://www.blacksesame.com.cn/",
        "纳芯微": "https://www.novosns.com/",
        "NOVOSENSE": "https://www.novosns.com/",
        "SiliconCompiler": "https://github.com/siliconcompiler/siliconcompiler",
        "OpenLane": "https://github.com/The-OpenROAD-Project/OpenLane",
        "SpecForge": "https://www.npmjs.com/package/specforge",
        "GitPLM": "https://github.com/charithmadhuranga/gitplm-product-Life-Cycle-Manager",
        "Dokuly": "https://github.com/Dokuly-PLM/dokuly",
        "PartCAD": "https://github.com/partcad/partcad",
        "Chipyard": "https://github.com/ucb-bar/chipyard",
        "mflowgen": "https://github.com/mflowgen/mflowgen",
        "CPM_Visualizer": "https://github.com/Grallistrix/CPM_Visualizer",
        "PERT-CPM-Analyzer": "https://github.com/imblackline/PERT-CPM-Analyzer",
        "criticalPathMethod": "https://github.com/motylele/criticalPathMethod",
        "awesome-opensource-hardware": "https://github.com/secworks/awesome-opensource-hardware",
        "QiMeng": "https://qimeng-ict.github.io/",
        "AllSpice": "https://www.allspice.io",
        "atopile": "https://github.com/atopile/atopile",
    })
    return url_map


def lookup_source_url(source_text: str, url_map: dict[str, str]) -> str:
    """根据来源文本查找 URL"""
    # 先尝试提取已有的 URL
    urls = extract_urls(source_text)
    if urls:
        return urls[0]

    # 移除日期部分
    clean = re.sub(r'\|\s*\d{4}.*$', '', source_text).strip()

    # 按逗号/分号分割来源
    sources = re.split(r'[,;，；、]\s*', clean)
    for src in sources:
        src = src.strip()
        # 精确匹配
        if src in url_map:
            return url_map[src]
        # 部分匹配
        for key, url in url_map.items():
            if key in src or src in key:
                return url

    return ""


def parse_step2_content(step2_text: str) -> list[SourceItem]:
    """从步骤二文本中解析检索源条目（格式：X.1 概况 / X.2 标题 / 来源：... / 核心发现：...）"""
    url_map = load_source_url_map()
    items: list[SourceItem] = []
    current_category = ""
    current_title = ""
    current_content = ""
    current_url = ""
    current_tags: list[str] = []

    def flush_item():
        nonlocal current_title, current_content, current_url, current_tags
        if current_category and current_title and current_content:
            clean_content = strip_date(current_content)
            if len(clean_content) > 150:
                clean_content = clean_content[:150] + '...'
            items.append(SourceItem(
                category=current_category,
                title=current_title,
                content=clean_content,
                source_url=current_url,
                tags=current_tags.copy(),
            ))
        current_title = ""
        current_content = ""
        current_url = ""
        current_tags = []

    for line in step2_text.strip().split('\n'):
        s = line.strip()
        if not s:
            continue

        # 跳过 F 分类中的 (1)(2) 编号行（在检测到 F 分类后再处理）
        if current_category == "F":
            gap_match = re.match(r'^\((\d+)\)\s*(.+)$', s)
            if gap_match:
                gap_text = gap_match.group(2).strip()
                pri_match = re.search(r'\(P[012]\)', gap_text)
                pri_tag = ""
                if pri_match:
                    pri_tag = pri_match.group(0).lower().replace('(', '').replace(')', '')
                gap_title = re.sub(r'\s*\(P[012]\)\s*', '', gap_text).strip()
                # 截取到 —— 之前作为标题，之后作为内容
                if '——' in gap_title:
                    parts = gap_title.split('——', 1)
                    gap_title = parts[0].strip()
                    gap_content = parts[1].strip()
                else:
                    gap_content = gap_title
                flush_item()
                current_category = "F"
                current_title = gap_title
                current_content = gap_content
                if pri_tag:
                    current_tags = [pri_tag]
                flush_item()
                continue

        # 检测条目：A.2 / B.2 / ... 排除 A.1/B.1 概况行
        item_match = re.match(r'^([A-F])\.(\d+)\s+(.+)$', s)
        if item_match:
            cat = item_match.group(1)
            num = item_match.group(2)
            title = item_match.group(3).strip()

            if num == "1":
                flush_item()
                current_category = cat
                continue

            flush_item()
            current_category = cat
            current_title = title
            continue

        # 检测"来源："行
        if s.startswith('来源：') or s.startswith('来源:'):
            source_text = s.replace('来源：', '').replace('来源:', '').strip()
            current_url = lookup_source_url(source_text, url_map)
            if '[新]' in source_text or '[更新]' in source_text:
                current_tags.append('new')
            if '[更新]' in source_text:
                current_tags.append('ref')
            continue

        # 检测"核心发现："行
        if s.startswith('核心发现：') or s.startswith('核心发现:'):
            current_content = s.replace('核心发现：', '').replace('核心发现:', '').strip()
            continue

    flush_item()
    return items


def parse_step4_items(step4_text: str) -> list[dict]:
    """从步骤四文本中解析建议条目（格式：P0建议 / 1. 标题 / 依据：... / 可行性：...）"""
    items: list[dict] = []
    current_pri = "P1"
    current_title = ""
    current_detail_parts: list[str] = []

    def flush():
        nonlocal current_title, current_detail_parts
        if current_title:
            detail = ' '.join(current_detail_parts)
            text = current_title
            if detail:
                text += ' — ' + detail[:120]
            items.append({"priority": current_pri, "text": text})
        current_title = ""
        current_detail_parts = []

    for line in step4_text.strip().split('\n'):
        s = line.strip()
        if not s or s.startswith('==='):
            continue

        # 检测优先级标题：P0建议 / P1建议 / P2建议
        pri_match = re.match(r'^(P[012])建', s)
        if pri_match:
            flush()
            current_pri = pri_match.group(1)
            continue

        # 检测编号条目：1. / 2. / 3.
        num_match = re.match(r'^(\d+)\.\s+(.+)$', s)
        if num_match:
            flush()
            current_title = num_match.group(2).strip()
            continue

        # 收集详情行
        if current_title:
            if s.startswith('依据：') or s.startswith('可行性：'):
                current_detail_parts.append(s)
            elif not s.startswith('P') and not s.startswith('==='):
                current_detail_parts.append(s)

    flush()
    return items


def extract_links_from_text(text: str) -> list[tuple[str, str]]:
    """从文本中提取 Markdown 链接，返回 [(文本, URL), ...]"""
    links = re.findall(r'\[([^\]]+)\]\((https?://[^)]+)\)', text)
    return links


# ============================================================
# HTML 生成
# ============================================================

def build_single_html(
    step2_text: str,
    step3_text: str,
    step4_text: str,
    step1_text: str = "",
) -> str:
    """生成单 HTML 多 Tab 报告"""

    source_items = parse_step2_content(step2_text)
    suggestion_items = parse_step4_items(step4_text)

    # ---- Tab 1: 概览 ----
    overview_html = build_overview_tab(source_items, suggestion_items, step3_text)

    # ---- Tab 2: 检索源汇总 ----
    sources_html = build_sources_tab(source_items)

    # ---- Tab 3: 建议 ----
    suggestions_html = build_suggestions_tab(suggestion_items, step4_text)

    # ---- Tab 4: 总结 ----
    summary_html = build_summary_tab(source_items, suggestion_items, step3_text)

    # ---- Tab 5: 分析 ----
    analysis_html = build_analysis_tab(step3_text)

    tabs = [
        ("tab-overview", "概览", overview_html, True),
        ("tab-sources", "检索源汇总", sources_html, False),
        ("tab-suggestions", "建议", suggestions_html, False),
        ("tab-summary", "总结", summary_html, False),
        ("tab-analysis", "分析", analysis_html, False),
    ]

    tab_buttons = ""
    tab_panels = ""
    for tab_id, tab_label, tab_body, is_active in tabs:
        active_cls = " active" if is_active else ""
        tab_buttons += f'        <button class="tab-btn{active_cls}" data-tab="{tab_id}">{tab_label}</button>\n'
        tab_panels += f'      <div class="tab-content{active_cls}" id="{tab_id}">\n{tab_body}\n      </div>\n'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>芯片IPD知识库报告</title>
<style>
{CSS_STYLE}
</style>
</head>
<body>

<div class="topbar">
  <div class="brand">芯片IPD知识库<span>| 行业动态报告</span></div>
</div>

<div class="tab-nav">
{tab_buttons}</div>

{tab_panels}
<div class="footer">
  <p>芯片 IPD 与项目管理知识库 · 自动生成 | 信息来源：行业媒体 + 企业公开资料 + GitHub + 学术论文</p>
</div>

<script>
(function() {{
  var btns = document.querySelectorAll('.tab-btn');
  btns.forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      btns.forEach(function(b) {{ b.classList.remove('active'); }});
      btn.classList.add('active');
      var panels = document.querySelectorAll('.tab-content');
      panels.forEach(function(p) {{ p.classList.remove('active'); }});
      document.getElementById(btn.dataset.tab).classList.add('active');
    }});
  }});
}})();
</script>
</body>
</html>"""


def build_overview_tab(
    source_items: list[SourceItem],
    suggestions: list[dict],
    step3_text: str,
) -> str:
    """构建概览 Tab：Hero + 指标卡片 + 执行摘要"""

    # 统计各分类条目数
    cat_counts: dict[str, int] = {}
    for item in source_items:
        cat_counts[item.category] = cat_counts.get(item.category, 0) + 1

    p0_count = sum(1 for s in suggestions if s["priority"] == "P0")
    p1_count = sum(1 for s in suggestions if s["priority"] == "P1")
    total_items = len(source_items)

    # 从 step3 提取核心洞察
    core_insight = ""
    for line in step3_text.split('\n'):
        s = line.strip()
        if '核心' in s or '关键' in s or '结论' in s:
            clean = re.sub(r'^#{1,4}\s*', '', s)
            clean = re.sub(r'^[-*]\s*', '', clean)
            if len(clean) > 15:
                core_insight = clean
                break
    if not core_insight:
        # 取 step3 前 200 字
        clean = re.sub(r'<[^>]+>', '', step3_text)
        clean = re.sub(r'#{1,4}\s*', '', clean)
        core_insight = clean.strip()[:200]

    cat_summary = "、".join(
        f"{CATEGORY_INFO.get(c, {}).get('name', c)}{n}条"
        for c, n in sorted(cat_counts.items())
    ) if cat_counts else ""

    return f"""    <div class="hero-card">
      <h1>芯片 IPD 行业动态报告</h1>
      <div class="sub">{cat_summary}</div>
    </div>

    <div class="metric-row">
      <div class="metric-card"><div class="num">{total_items}</div><div class="lbl">信息条目</div></div>
      <div class="metric-card"><div class="num">{len(cat_counts)}</div><div class="lbl">检索分类</div></div>
      <div class="metric-card warn"><div class="num">{p0_count}</div><div class="lbl">P0 建议</div></div>
      <div class="metric-card good"><div class="num">{p1_count + p0_count}</div><div class="lbl">行动建议</div></div>
      <div class="metric-card"><div class="num">{len(source_items)}</div><div class="lbl">信息来源</div></div>
    </div>

    <div class="section-block">
      <h2>执行摘要</h2>
      <div class="insight-block">
        <h4>本期核心结论</h4>
        <p>{core_insight}</p>
      </div>
    </div>

    <div class="section-block">
      <h2>各分类概况</h2>
      <div class="source-grid">
        {build_category_summary_cards(source_items)}
      </div>
    </div>"""


def build_category_summary_cards(items: list[SourceItem]) -> str:
    """按分类生成概览卡片"""
    grouped: dict[str, list[SourceItem]] = {}
    for item in items:
        grouped.setdefault(item.category, []).append(item)

    cards = ""
    for cat in ["A", "B", "C", "D", "E", "F"]:
        if cat not in grouped:
            continue
        cat_info = CATEGORY_INFO.get(cat, {"name": cat, "css_class": "cat-a"})
        cat_items = grouped[cat]
        bullets = "".join(
            f'<li><a href="{i.source_url}" target="_blank" rel="noopener">{i.title}</a></li>'
            if i.source_url else f'<li>{i.title}</li>'
            for i in cat_items[:3]
        )
        more = f'<p style="font-size:12px;color:var(--muted);">还有 {len(cat_items) - 3} 条，见"检索源汇总"</p>' if len(cat_items) > 3 else ""
        cards += f"""      <div class="source-card {cat_info['css_class']}">
        <div class="cat-label">{cat} · {cat_info['name']}（{len(cat_items)} 条）</div>
        <ul style="font-size:13px;margin-left:18px;line-height:1.8;">{bullets}</ul>
        {more}
      </div>"""

    return cards


def build_sources_tab(items: list[SourceItem]) -> str:
    """构建检索源汇总 Tab：按分类展示条目卡片，不含日期，含来源链接"""
    if not items:
        return """    <div class="section-block">
      <h2>检索源汇总</h2>
      <p style="color:var(--muted);">本期无条目数据，请检查步骤二输入。</p>
    </div>"""

    grouped: dict[str, list[SourceItem]] = {}
    for item in items:
        grouped.setdefault(item.category, []).append(item)

    sections = ""
    for cat in ["A", "B", "C", "D", "E", "F"]:
        if cat not in grouped:
            continue
        cat_info = CATEGORY_INFO.get(cat, {"name": cat, "css_class": "cat-a"})
        cat_items = grouped[cat]

        cards = ""
        for item in cat_items:
            tags_html = ""
            if item.tags:
                tag_labels = {"new": "新", "ref": "参考", "risk": "风险", "warn": "警告"}
                tags_html = '<div class="tag-row">' + ''.join(
                    f'<span class="tag tag-{t}">{tag_labels.get(t, t)}</span>'
                    for t in item.tags
                ) + '</div>'

            link_html = ""
            if item.source_url:
                link_html = f'<a href="{item.source_url}" target="_blank" rel="noopener" class="src-link">查看来源 →</a>'

            cards += f"""      <div class="source-card {cat_info['css_class']}">
        <div class="cat-label">{item.title}</div>
        <p>{item.content}</p>
        {tags_html}
        {link_html}
      </div>"""

        sections += f"""    <div class="section-block">
      <h2>{cat} · {cat_info['name']} <span class="cnt">{len(cat_items)} 条</span></h2>
      <div class="source-grid">
{cards}      </div>
    </div>"""

    return f"""    <div class="section-block">
      <h2>检索源汇总</h2>
      <p style="color:var(--muted);margin-bottom:24px;">按六类检索源分类展示，已移除日期信息，保留来源链接。</p>
    </div>
{sections}"""


def build_suggestions_tab(items: list[dict], step4_full: str) -> str:
    """构建建议 Tab"""
    if not items:
        content = re.sub(r'<[^>]+>', '', step4_full)
        return f"""    <div class="section-block">
      <h2>纳芯微发展建议</h2>
      <div class="full-card"><p>{content}</p></div>
    </div>"""

    cards = ""
    for s in items:
        pri = s["priority"]
        cls = pri.lower()
        cards += f"""      <div class="rec-card {cls}">
        <div class="pri">{pri} · {'立即行动' if pri == 'P0' else '本季推进' if pri == 'P1' else '年内规划'}</div>
        <p>{s['text']}</p>
      </div>"""

    return f"""    <div class="section-block">
      <h2>纳芯微发展建议</h2>
      {cards}
    </div>"""


def build_summary_tab(items: list[SourceItem], suggestions: list[dict], step3_text: str) -> str:
    """构建总结 Tab：知识缺口 + 关键结论"""
    # 从 step3 提取关键结论
    insight_text = ""
    for line in step3_text.split('\n'):
        s = line.strip()
        if re.match(r'^#{2,4}', s):
            clean = re.sub(r'^#{2,4}\s*', '', s)
            insight_text += f'<h4>{clean}</h4>\n'
        elif len(s) > 20:
            clean = re.sub(r'^[-*]\s*', '', s)
            insight_text += f'<p>{clean}</p>\n'

    # 从 items 中找出 tag 含 "risk" 或 "warn" 的条目作为关注点
    risk_items = [i for i in items if 'risk' in i.tags or 'warn' in i.tags]

    risk_html = ""
    if risk_items:
        risk_html = '<h4>需关注的风险信号</h4><ul>'
        for item in risk_items:
            risk_html += f'<li><b>{item.title}</b>：{item.content[:100]}'
            if item.source_url:
                risk_html += f' <a href="{item.source_url}" target="_blank" rel="noopener">[来源]</a>'
            risk_html += '</li>'
        risk_html += '</ul>'

    p0_items = [s for s in suggestions if s["priority"] == "P0"]
    p0_html = ""
    if p0_items:
        p0_html = '<h4>P0 高优先级行动</h4><ol>'
        for s in p0_items:
            p0_html += f'<li>{s["text"]}</li>'
        p0_html += '</ol>'

    return f"""    <div class="section-block">
      <h2>本期总结</h2>
      <div class="full-card">
        {insight_text or '<p>详细分析见"分析"标签页。</p>'}
      </div>
    </div>
    <div class="section-block">
      <h2>行动要点</h2>
      <div class="full-card">
        {risk_html}
        {p0_html}
      </div>
    </div>"""


def build_analysis_tab(step3_text: str) -> str:
    """构建分析 Tab：将步骤三内容（维度X：... | 现象：... | 原因：... | 启示：...）格式化"""
    sections_html = ""

    for line in step3_text.strip().split('\n'):
        s = line.strip()
        if not s:
            continue

        # 维度标题：维度X：...
        dim_match = re.match(r'^维度([一二三四五六七八九十])[：:](.+)$', s)
        if dim_match:
            dim_num = dim_match.group(1)
            rest = dim_match.group(2)

            # 按 | 分割各字段
            parts = [p.strip() for p in rest.split('|')]

            # 维度名是第一个 | 之前的内容
            dim_name = parts[0] if parts else ""

            # 其他字段
            fields = {}
            for part in parts[1:]:
                kv = re.split(r'[：:]', part, maxsplit=1)
                if len(kv) == 2:
                    fields[kv[0].strip()] = kv[1].strip()

            phenomenon = fields.get('现象', '')
            reason = fields.get('原因', '')
            insight = fields.get('纳芯微启示', fields.get('启示', ''))

            html = f'<h3>维度{dim_num}：{dim_name}</h3>'
            if phenomenon:
                html += f'<div class="insight-block"><h4>现象</h4><p>{phenomenon}</p></div>'
            if reason:
                html += f'<div class="insight-block"><h4>原因分析</h4><p>{reason}</p></div>'
            if insight:
                html += f'<div class="insight-block"><h4>对纳芯微的启示</h4><p>{insight}</p></div>'
            sections_html += html
            continue

        # 普通行
        if len(s) > 10:
            sections_html += f'<p>{s}</p>'

    return f"""    <div class="section-block">
      <h2>行业对比分析</h2>
      <div class="full-card">
        {sections_html}
      </div>
    </div>"""


# ============================================================
# 微信推送
# ============================================================

def build_wechat_content(
    date_str: str,
    source_items: list[SourceItem],
    suggestions: list[dict],
    step3_text: str,
) -> str:
    """构建微信推送内容（含主页概览 + 来源链接）"""
    # 概览摘要
    clean_step3 = re.sub(r'<[^>]+>', '', step3_text)
    core_lines = [l.strip() for l in clean_step3.split('\n') if len(l.strip()) > 20]
    overview = core_lines[0][:150] if core_lines else "本期芯片IPD行业动态更新"

    # 按分类汇总
    grouped: dict[str, list[SourceItem]] = {}
    for item in source_items:
        grouped.setdefault(item.category, []).append(item)

    cat_sections = ""
    for cat in ["A", "B", "C", "D", "E", "F"]:
        if cat not in grouped:
            continue
        cat_info = CATEGORY_INFO.get(cat, {"name": cat})
        cat_items = grouped[cat]
        bullets = ""
        for item in cat_items[:4]:
            link_part = f' <a href="{item.source_url}">[来源]</a>' if item.source_url else ""
            bullets += f'<li>{item.title}：{item.content[:80]}{link_part}</li>'
        cat_sections += f'<h4>{cat}. {cat_info["name"]}（{len(cat_items)} 条）</h4><ul>{bullets}</ul>'

    # P0 建议
    p0_items = [s for s in suggestions if s["priority"] == "P0"]
    p0_html = ""
    if p0_items:
        p0_html = '<h4>P0 行动建议</h4><ol>'
        for s in p0_items[:3]:
            p0_html += f'<li>{s["text"]}</li>'
        p0_html += '</ol>'

    return f"""<h3>芯片IPD行业更新 ({date_str})</h3>
<p><b>摘要：</b>{overview}</p>
<hr>
{cat_sections}
{p0_html}
<hr>
<p style="font-size:11px;color:#888;">完整报告：芯片项目/芯片研发自动排期/ipd_knowledge_base/reports/{date_str}/</p>"""


def send_wechat(title: str, content: str) -> bool:
    """通过 PushPlus 发送微信消息"""
    if not PUSHPLUS_CONFIG.exists():
        print(f"[SKIP] PushPlus 配置文件不存在: {PUSHPLUS_CONFIG}")
        return False
    try:
        cfg = json.loads(PUSHPLUS_CONFIG.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[SKIP] PushPlus 配置文件读取失败: {e}")
        return False

    token = cfg.get("pushplus_token", "")
    if not token:
        print("[SKIP] PushPlus Token 未配置")
        return False

    payload = json.dumps({
        "token": token, "title": title, "content": content, "template": "html",
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            PUSHPLUS_URL, data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if result.get("code") == 200:
                print(f"[SUCCESS] 已推送到微信 | 标题: {title}")
                return True
            print(f"[FAIL] PushPlus 返回: {result.get('msg', '')}")
            return False
    except Exception as e:
        print(f"[FAIL] 网络错误: {e}")
        return False


# ============================================================
# 主流程
# ============================================================

def run_full_report(
    step1: str = "",
    step2: str = "",
    step3: str = "",
    step4: str = "",
    no_push: bool = False,
) -> None:
    """完整五步报告模式：生成单 HTML 多 Tab 报告 + 微信推送"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 生成单 HTML
    html_content = build_single_html(
        step2_text=step2,
        step3_text=step3,
        step4_text=step4,
        step1_text=step1,
    )
    output_path = OUTPUT_DIR / "index.html"
    output_path.write_text(html_content, encoding="utf-8")
    print(f"[OK] 报告已生成: {output_path}")

    # 统计信息
    source_items = parse_step2_content(step2)
    print(f"  信息条目: {len(source_items)}")
    cat_counts: dict[str, int] = {}
    for item in source_items:
        cat_counts[item.category] = cat_counts.get(item.category, 0) + 1
    for cat, cnt in sorted(cat_counts.items()):
        name = CATEGORY_INFO.get(cat, {}).get('name', cat)
        print(f"  {cat} · {name}: {cnt} 条")

    suggestions = parse_step4_items(step4)
    p0 = sum(1 for s in suggestions if s["priority"] == "P0")
    print(f"  建议: P0×{p0} P1×{len(suggestions) - p0}")

    # 微信推送
    if not no_push:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        wechat_content = build_wechat_content(now_str, source_items, suggestions, step3)
        wechat_title = f"芯片IPD更新 ({datetime.now().strftime('%Y-%m-%d')})"
        success = send_wechat(wechat_title, wechat_content)
        # 记录推送日志
        log_path = OUTPUT_DIR / "push_log.txt"
        log_entry = f"{now_str} | {wechat_title} | {'成功' if success else '失败'}\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)
    else:
        print("[SKIP] 跳过微信推送")

    print("\n[DONE]")


def run_legacy_mode(no_push: bool = False) -> None:
    """存量扫描模式：扫描 .md 知识文件生成单页面报告"""
    print(f"=== IPD 知识库存量扫描 ===\n")

    files_data: list[dict] = []
    for md_file in sorted(KNOWLEDGE_BASE.glob("*.md")):
        if md_file.name in ("00_README.md", "检索源清单.md"):
            continue
        text = md_file.read_text(encoding="utf-8")
        title = ""
        sections: list[str] = []
        for line in text.split("\n"):
            if line.startswith("# ") and not title:
                title = line.lstrip("# ").strip()
            if line.startswith("## "):
                sections.append(line.lstrip("## ").strip())
        word_count = len(re.sub(r"\s+", "", text))
        files_data.append({
            "filename": md_file.name,
            "title": title or md_file.stem,
            "sections": sections,
            "section_count": len(sections),
            "word_count": word_count,
        })

    stats = {
        "知识主题": len(files_data),
        "内容章节": sum(f["section_count"] for f in files_data),
        "累计字数": f"{sum(f['word_count'] for f in files_data) // 1000}k",
        "覆盖维度": 9,
    }

    files_html = ""
    for f in files_data:
        secs = "".join(f"<li>{s}</li>" for s in f["sections"])
        files_html += f"""      <div class="full-card">
        <h3>{f['title']}</h3>
        <p style="font-size:13px;color:var(--muted);">{f['section_count']} 个章节 · 约 {f['word_count']} 字</p>
        <ul style="margin-left:20px;font-size:14px;">{secs}</ul>
      </div>"""

    stats_html = ""
    for label, val in stats.items():
        stats_html += f'      <div class="metric-card"><div class="num">{val}</div><div class="lbl">{label}</div></div>\n'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>芯片 IPD 知识库综合报告</title>
<style>{CSS_STYLE}</style>
</head>
<body>
<div class="topbar">
  <div class="brand">芯片IPD知识库<span>| 存量扫描</span></div>
</div>
<div class="tab-content active" style="display:block; padding:32px 40px; max-width:1000px; margin:0 auto;">
  <div class="hero-card">
    <h1>芯片 IPD 知识库综合报告</h1>
    <div class="sub">存量扫描模式</div>
  </div>
  <div class="metric-row">
{stats_html}  </div>
  <div class="section-block">
    <h2>知识文件一览</h2>
{files_html}  </div>
</div>
<div class="footer">
  <p>芯片 IPD 与项目管理知识库 · 自动生成</p>
</div>
</body>
</html>"""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "index.html"
    output_path.write_text(html, encoding="utf-8")
    print(f"[OK] 报告已生成: {output_path}")
    for label, val in stats.items():
        print(f"  {label}: {val}")

    if not no_push:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        title = f"芯片IPD知识库报告"
        summary_items = "".join(
            f"<li>{f['title']} — {f['section_count']} 章节</li>"
            for f in files_data
        )
        content = f"""<h3>芯片IPD知识库报告</h3>
<p>存量扫描：{len(files_data)} 个知识主题，{sum(f['word_count'] for f in files_data)} 字</p>
<hr><ul>{summary_items}</ul>
<hr><p style="font-size:11px;color:#888;">完整报告见 output/index.html</p>"""
        send_wechat(title, content)
        log_path = OUTPUT_DIR / "push_log.txt"
        log_entry = f"{now_str} | {title} | 存量扫描\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)

    print("\n[DONE]")


def main():
    parser = argparse.ArgumentParser(description="IPD 知识库综合报告生成器（单 HTML 多 Tab）")
    parser.add_argument("--step1", default="", help="步骤一：检索源信息获取")
    parser.add_argument("--step2", default="", help="步骤二：六类信息汇总")
    parser.add_argument("--step3", default="", help="步骤三：跨类对比与行业分析")
    parser.add_argument("--step4", default="", help="步骤四：纳芯微发展建议")
    parser.add_argument("--no-push", action="store_true", help="不推送到微信")
    args = parser.parse_args()

    has_full = any([args.step1, args.step2, args.step3, args.step4])

    if has_full:
        if not args.step2:
            print("[ERROR] 完整模式至少需要 --step2")
            sys.exit(1)
        run_full_report(
            step1=args.step1,
            step2=args.step2,
            step3=args.step3 or "",
            step4=args.step4 or "",
            no_push=args.no_push,
        )
    else:
        run_legacy_mode(no_push=args.no_push)


if __name__ == "__main__":
    main()
