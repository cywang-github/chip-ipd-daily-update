"""IPD 知识库每日自动更新脚本

运行环境：GitHub Actions（ubuntu-latest）
调度时间：北京时间 8:30（UTC 0:30）
工作流：搜索 → LLM 分析 → HTML 报告 → 微信推送

依赖环境变量（GitHub Secrets）：
    DEEPSEEK_API_KEY  — DeepSeek API 密钥
    PUSHPLUS_TOKEN    — PushPlus 微信推送 Token
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import NamedTuple

# ============================================================
# 配置
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "ipd_knowledge_base" / "output"

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
PUSHPLUS_URL = "https://www.pushplus.plus/send"

beijing_tz = timezone(timedelta(hours=8))
TODAY = datetime.now(beijing_tz).strftime("%Y-%m-%d")

# 搜索查询（每分类 1 条，聚焦最近 7 天增量信息）
SEARCH_QUERIES = [
    ("A-国外公司", "semiconductor NPI new product TI Infineon NXP 2026 latest"),
    ("B-国内公司", "纳芯微 比亚迪半导体 国产芯片 车规 最新进展 2026"),
    ("C-GitHub", "chip design PLM workflow github 2026 latest"),
    ("D-学术", "ISSCC HotChips DAC semiconductor 2026 paper"),
    ("E-标准", "AEC-Q100 ISO26262 automotive semiconductor 2026 update"),
    ("F-补充", "芯片 IPD 集成产品开发 敏捷 半导体 新方法 2026"),
]

ANALYSIS_SYSTEM_PROMPT = """你是半导体IPD分析师。根据搜索结果，仅报告最近7天内的**新增/更新**信息。

输出格式（Markdown，仅输出有内容的分类）：

## 步骤二：增量信息汇总
### A. 国外公司
- **[新]** 或 **[更新]** 标题 | 来源URL
  - 核心内容（1-2句）

### B-F 同上

## 步骤三：关键变化
- 一句话分析（现象+启示），最多3条

## 步骤四：建议
### P0
- 建议 | 可行性

规则：
- 无新信息的分类直接跳过
- 禁止使用：赋能、抓手、闭环、对齐、颗粒度、底层逻辑"""


def get_api_keys() -> tuple[str, str]:
    """获取 API 密钥：优先环境变量，fallback 本地配置文件"""
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    pushplus_token = os.environ.get("PUSHPLUS_TOKEN", "")

    if not deepseek_key:
        settings_path = Path.home() / ".claude" / "settings.json"
        if settings_path.exists():
            cfg = json.loads(settings_path.read_text(encoding="utf-8"))
            deepseek_key = cfg.get("env", {}).get("ANTHROPIC_AUTH_TOKEN", "")

    if not pushplus_token:
        config_path = SCRIPT_DIR.parent / "芯片导出工具" / "pushplus_config.json"
        if config_path.exists():
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            pushplus_token = cfg.get("pushplus_token", "")

    return deepseek_key, pushplus_token


# ============================================================
# Step 1: 网页搜索
# ============================================================

def search_web(query: str, max_results: int = 5) -> list[dict]:
    """使用 DuckDuckGo 搜索，返回 [{"title": ..., "href": ..., "body": ...}]"""
    try:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "href": r.get("href", ""),
                    "body": r.get("body", ""),
                })
        return results
    except Exception as e:
        print(f"  [WARN] 搜索失败 '{query[:40]}...': {e}")
        return []


def run_all_searches() -> list[dict]:
    """执行所有搜索查询，去重后返回"""
    print("=" * 60)
    print("Step 1: 网页搜索")
    print("=" * 60)

    all_results: list[dict] = []
    seen_urls: set[str] = set()

    for category, query in SEARCH_QUERIES:
        print(f"\n[{category}] {query[:60]}...")
        results = search_web(query)
        new_count = 0
        for r in results:
            if r["href"] and r["href"] not in seen_urls:
                seen_urls.add(r["href"])
                r["category"] = category
                all_results.append(r)
                new_count += 1
        print(f"  获取 {len(results)} 条，新增 {new_count} 条")
        time.sleep(1.5)  # 避免被限流

    print(f"\n总计去重后: {len(all_results)} 条")
    return all_results


# ============================================================
# Step 2-4: LLM 分析与建议
# ============================================================

def format_search_results(results: list[dict]) -> str:
    """将搜索结果格式化为 LLM 可读的文本"""
    lines: list[str] = []
    for i, r in enumerate(results, 1):
        cat = r.get("category", "?")
        lines.append(f"[{i}] [{cat}] {r['title']}")
        lines.append(f"    URL: {r['href']}")
        lines.append(f"    摘要: {r['body']}")
        lines.append("")
    return "\n".join(lines)


def call_deepseek(prompt: str, system: str = "", max_tokens: int = 8192) -> str:
    """调用 DeepSeek API（Anthropic 兼容端点）"""
    api_key, _ = get_api_keys()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body = json.dumps({
        "model": DEEPSEEK_MODEL,
        "max_tokens": max_tokens,
        "messages": messages,
    }).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    req = urllib.request.Request(DEEPSEEK_URL, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    return data["choices"][0]["message"]["content"]


def run_llm_analysis(results: list[dict]) -> str:
    """调用 DeepSeek 对搜索结果进行完整分析，返回 Markdown 文本"""
    print("\n" + "=" * 60)
    print("Step 2-4: LLM 分析（DeepSeek API）")
    print("=" * 60)

    search_text = format_search_results(results)
    prompt = f"""以下是{TODAY}半导体行业搜索结果（{len(results)}条）。仅报告真正新增或更新的信息，无新信息则标注"本日无重大更新"。

=== 搜索结果 ===
{search_text}

=== 请分析 ===
今天是{TODAY}，仅关注最近7天内发布的新内容。旧闻或已稳定趋势标注为[确认]或直接跳过。"""

    print(f"  输入: {len(results)} 条搜索结果")
    response = call_deepseek(prompt, system=ANALYSIS_SYSTEM_PROMPT, max_tokens=4096)
    print(f"  输出: {len(response)} 字符")
    return response


def parse_llm_output(markdown_text: str) -> tuple[str, str, str]:
    """从 LLM 输出中提取步骤二、三、四的文本"""
    step2 = ""
    step3 = ""
    step4 = ""

    lines = markdown_text.split("\n")
    current_section = ""
    section_lines: list[str] = []

    for line in lines:
        if line.strip().startswith("## 步骤二"):
            if current_section == "step2":
                step2 = "\n".join(section_lines).strip()
            elif current_section == "step3":
                step3 = "\n".join(section_lines).strip()
            elif current_section == "step4":
                step4 = "\n".join(section_lines).strip()
            current_section = "step2"
            section_lines = []
        elif line.strip().startswith("## 步骤三"):
            if current_section == "step2":
                step2 = "\n".join(section_lines).strip()
            current_section = "step3"
            section_lines = []
        elif line.strip().startswith("## 步骤四"):
            if current_section == "step3":
                step3 = "\n".join(section_lines).strip()
            current_section = "step4"
            section_lines = []
        else:
            section_lines.append(line)

    # 处理最后一个 section
    if current_section == "step2":
        step2 = "\n".join(section_lines).strip()
    elif current_section == "step3":
        step3 = "\n".join(section_lines).strip()
    elif current_section == "step4":
        step4 = "\n".join(section_lines).strip()

    return step2, step3, step4


# ============================================================
# Step 5: HTML 报告 + 微信推送
# ============================================================

def send_wechat(title: str, content: str) -> bool:
    """通过 PushPlus 发送微信消息"""
    _, pushplus_token = get_api_keys()
    if not pushplus_token:
        print("[SKIP] PUSHPLUS_TOKEN 未配置")
        return False

    payload = json.dumps({
        "token": pushplus_token,
        "title": f"芯片IPD更新 ({TODAY})",
        "content": content,
        "template": "html",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            PUSHPLUS_URL, data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("code") == 200:
                print(f"[SUCCESS] 微信推送成功: {title}")
                return True
            print(f"[FAIL] PushPlus 返回: {result.get('msg', 'unknown')}")
            return False
    except Exception as e:
        print(f"[FAIL] PushPlus 网络错误: {e}")
        return False


def build_wechat_summary(step2: str, step3: str, step4: str) -> str:
    """构建微信推送摘要（精简版，含分类汇总和建议）"""
    # 提取各分类统计
    cat_counts: dict[str, int] = {}
    for line in step2.split("\n"):
        if line.startswith("### ") and len(line) > 4:
            cat_name = line[4:].strip()
            cat_counts[cat_name] = 0
        if line.startswith("- **") or line.startswith("- **[新]") or line.startswith("- **[更新]"):
            for cat in cat_counts:
                cat_counts[cat] += 1

    cat_html = ""
    for name, cnt in cat_counts.items():
        cat_html += f"<li><b>{name}</b>：{cnt} 条</li>"

    # 提取 P0 建议
    p0_items: list[str] = []
    in_p0 = False
    for line in step4.split("\n"):
        if "P0" in line and "立即行动" in line:
            in_p0 = True
            continue
        if "P1" in line or "P2" in line:
            in_p0 = False
            continue
        if in_p0 and line.strip().startswith("-"):
            p0_items.append(line.strip("- ").strip())

    p0_html = ""
    for item in p0_items[:3]:
        p0_html += f"<li>{item}</li>"

    # 提取关键发现（步骤三第一条现象）
    key_findings = ""
    phenomenon_count = 0
    for line in step3.split("\n"):
        if line.strip().startswith("现象") and phenomenon_count < 2:
            key_findings += f"<li>{line.strip()}</li>"
            phenomenon_count += 1

    return f"""<h3>芯片IPD行业每日更新</h3>
<p style="color:#666;">{TODAY} 自动生成 | 下次更新：明天 8:30</p>
<hr>
<h4>分类统计</h4>
<ul>{cat_html}</ul>
<h4>关键发现</h4>
<ul>{key_findings if key_findings else '<li>详见完整报告</li>'}</ul>
<h4>P0 行动建议</h4>
<ol>{p0_html if p0_html else '<li>详见完整报告</li>'}</ol>
<hr>
<p style="font-size:11px;color:#888;">完整报告见 GitHub Actions 运行日志</p>"""


def build_html_report(step2: str, step3: str, step4: str) -> str:
    """构建完整 HTML 报告（简化单页版）"""
    # 将 Markdown 转换为简单 HTML
    def md_to_html(text: str) -> str:
        import re
        lines = text.split("\n")
        html_lines: list[str] = []
        in_list = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                continue
            if stripped.startswith("### "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f'<h3 style="margin-top:24px;">{stripped[4:]}</h3>')
            elif stripped.startswith("#### "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f'<h4 style="margin-top:16px;color:#374151;">{stripped[5:]}</h4>')
            elif stripped.startswith("- **"):
                if not in_list:
                    html_lines.append('<ul style="margin-left:20px;">')
                    in_list = True
                item = stripped[2:]
                item = item.replace("**[新]**", '<span class="tag tag-new">新</span> ')
                item = item.replace("**[更新]**", '<span class="tag tag-ref">更新</span> ')
                item = item.replace("**[确认]**", '<span class="tag tag-ok">确认</span> ')
                item = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', item)
                item = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', item)
                html_lines.append(f"<li>{item}</li>")
            elif stripped.startswith("- "):
                if not in_list:
                    html_lines.append('<ul style="margin-left:20px;">')
                    in_list = True
                item = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', stripped[2:])
                item = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', item)
                html_lines.append(f"<li>{item}</li>")
            else:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                para = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', stripped)
                para = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', para)
                html_lines.append(f"<p>{para}</p>")
        if in_list:
            html_lines.append("</ul>")
        return "\n".join(html_lines)

    step2_html = md_to_html(step2)
    step3_html = md_to_html(step3)
    step4_html = md_to_html(step4)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>芯片IPD每日更新 {TODAY}</title>
<style>
    :root {{
        --bg: #f5f5f5; --card: #fff; --text: #1a1a2e; --muted: #6b7280;
        --border: #e5e7eb; --accent: #2563eb; --accent-light: #eff6ff;
        --red: #dc2626; --amber: #d97706; --green: #059669;
        --radius: 8px;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
        background: var(--bg); color: var(--text); line-height: 1.7; font-size: 14px;
    }}
    .topbar {{
        background: #0f172a; color: #fff; padding: 14px 28px;
        display: flex; align-items: center; justify-content: space-between;
    }}
    .topbar .brand {{ font-weight: 700; font-size: 16px; }}
    .topbar .brand span {{ opacity: .5; font-weight: 400; font-size: 13px; margin-left: 8px; }}
    .container {{ max-width: 960px; margin: 0 auto; padding: 28px 20px; }}
    .hero {{
        background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
        color: #fff; padding: 36px; border-radius: 12px; margin-bottom: 28px;
    }}
    .hero h1 {{ font-size: 24px; margin-bottom: 6px; }}
    .hero .sub {{ font-size: 13px; opacity: .6; }}
    .section {{
        background: var(--card); border-radius: var(--radius); padding: 28px;
        margin-bottom: 20px; box-shadow: 0 1px 2px rgba(0,0,0,.04);
    }}
    .section h2 {{
        font-size: 18px; margin-bottom: 18px; padding-bottom: 10px;
        border-bottom: 2px solid var(--accent);
    }}
    .tag {{ display: inline-block; padding: 1px 8px; border-radius: 100px; font-size: 11px; font-weight: 600; }}
    .tag-new {{ background: #f0fdf4; color: #166534; }}
    .tag-ref {{ background: var(--accent-light); color: var(--accent); }}
    .tag-ok {{ background: #ecfdf5; color: #059669; }}
    ul, ol {{ margin-bottom: 8px; }}
    li {{ margin-bottom: 4px; }}
    a {{ color: var(--accent); }}
    .footer {{ text-align: center; font-size: 12px; color: var(--muted); padding: 24px; }}
</style>
</head>
<body>
<div class="topbar">
    <div class="brand">芯片IPD知识库<span>| 每日自动更新</span></div>
    <div style="font-size:13px;opacity:.7;">{TODAY}</div>
</div>
<div class="container">
    <div class="hero">
        <h1>芯片 IPD 行业每日更新</h1>
        <div class="sub">自动搜索 + LLM 分析 + 微信推送 | 每日 8:30 AM 更新</div>
    </div>

    <div class="section">
        <h2>六类信息汇总</h2>
        {step2_html}
    </div>

    <div class="section">
        <h2>跨类对比分析</h2>
        {step3_html}
    </div>

    <div class="section">
        <h2>纳芯微发展建议</h2>
        {step4_html}
    </div>
</div>
<div class="footer">
    <p>芯片IPD知识库 · 云端自动生成 · 下次更新：{TODAY} 明天 8:30</p>
</div>
</body>
</html>"""


# ============================================================
# 主流程
# ============================================================

def main():
    print(f"\n{'=' * 60}")
    print(f"IPD 知识库每日自动更新 — {TODAY}")
    print(f"{'=' * 60}")

    # 检查 API 密钥
    deepseek_key, pushplus_token = get_api_keys()
    if not deepseek_key:
        print("[FATAL] DEEPSEEK_API_KEY 未配置（设置环境变量或 ~/.claude/settings.json）")
        sys.exit(1)
    if not pushplus_token:
        print("[WARN] PUSHPLUS_TOKEN 未配置，将跳过微信推送")

    # Step 1: 搜索
    search_results = run_all_searches()
    if not search_results:
        print("[ERROR] 所有搜索均失败，退出")
        sys.exit(1)

    # Step 2-4: LLM 分析
    try:
        llm_output = run_llm_analysis(search_results)
    except Exception as e:
        print(f"[FATAL] LLM 分析失败: {e}")
        sys.exit(1)

    step2, step3, step4 = parse_llm_output(llm_output)
    if not step2:
        print("[ERROR] LLM 未输出步骤二，使用原始输出作为步骤二")
        step2 = llm_output

    # Step 5: 生成 HTML 报告
    print("\n" + "=" * 60)
    print("Step 5: 生成报告 + 微信推送")
    print("=" * 60)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    html_content = build_html_report(step2, step3, step4)
    html_path = OUTPUT_DIR / "index.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"[OK] HTML 报告: {html_path} ({len(html_content)} 字符)")

    # 微信推送
    if pushplus_token:
        wechat_content = build_wechat_summary(step2, step3, step4)
        success = send_wechat(f"芯片IPD更新 ({TODAY})", wechat_content)

        log_path = OUTPUT_DIR / "push_log.txt"
        log_entry = f"{TODAY} | 芯片IPD更新 | {'成功' if success else '失败'}\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)
    else:
        print("[SKIP] 微信推送（PUSHPLUS_TOKEN 未配置）")

    print(f"\n{'=' * 60}")
    print(f"[DONE] {TODAY} IPD 每日更新完成")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
