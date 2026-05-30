# CLAUDE.md — 芯片研发自动排期

## 项目概述

芯片研发自动排期工具，基于 IPD 流程和 CPM（关键路径法），对纳芯微传感器芯片从立项到量产的完整研发周期进行排期管理。

## 当前实现

以 **NSOPA901x 高精度运放**（AEC-Q100 Grade 1）为默认模板，覆盖完整 IPD 五阶段流程。支持多项目管理、实际日期映射、进度跟踪和 CSV 导出。

### 技术栈

- HTML 单页应用，纯原生 JS，无框架依赖
- CPM 算法：正向传播（ES/EF）→ 反向传播（LS/LF）→ 浮动计算 → 关键路径识别
- 甘特图可视化，SVG 绘制依赖箭头
- localStorage 持久化（键名 `chip_schedule_projects`）

### 核心功能

| 功能 | 说明 |
|------|------|
| CPM 关键路径 | 自动计算所有任务的 ES/EF/LS/LF/浮动，识别零浮动关键路径 |
| 多项目管理 | 创建/切换项目，支持从模板创建或空白项目 |
| 实际日期映射 | 设定项目启动日期，将周数自动换算为日历日期 |
| 进度跟踪 | 任务三态标记（未开始/进行中/已完成），甘特条视觉反馈 |
| CSV 导出 | 纯 JS 生成 UTF-8 BOM CSV，Excel 直接打开中文不乱码 |
| 筛选 | 按 IPD 阶段、负责团队筛选任务 |
| 甘特图交互 | 悬停 tooltip、点击详情面板、关键路径高亮、依赖箭头 |

### IPD 五阶段

| 阶段 | 任务数 | 说明 |
|------|--------|------|
| 概念阶段 | 4 | 市场调研、技术可行性、初步规格、商业论证 |
| 计划阶段 | 7 | PRD、架构设计、IP选型、DFMEA、DR0评审 |
| 开发阶段 | 9 | 电路设计、前仿真、版图、后仿真、DR1评审 |
| 验证阶段 | 9 | 流片、CP/FT测试、AEC-Q100、DR2评审 |
| 发布阶段 | 7 | 工程样片、客户导入、量产爬坡、良率提升、DR3 |

### 关键路径

关键路径总工期约 77 周（~18 个月），路径为：
市场调研 → 可行性评估 → 规格定义 → PRD → 架构设计 → IP选型 → DR0 → 核心电路 → 前仿真 → 版图 → 后仿真 → DR1 → Tape-out → 流片(8w) → CP测试 → AEC-Q100(10w) → DR2 → 样片 → 爬坡 → 良率提升 → 量产发布

### 数据模型

```js
// localStorage: chip_schedule_projects
{
  version: 2,
  activeProjectId: "proj_default",
  projects: {
    "proj_default": {
      id, name, subtitle, startDate, createdAt, updatedAt,
      tasks: [{ id, name, phase, team, dur, deps[], milestone?, info?, status }]
    }
  }
}
```

### 关键文件

| 文件 | 说明 |
|------|------|
| `index.html` | 主页面：数据模型 + CPM 算法 + 甘特图渲染 + 多项目管理 + 导出 |
| `ipd_knowledge_base/` | IPD 定时知识积累任务基础设施 |

### IPD 定时知识积累

通过 `ipd-knowledge-update` skill 驱动的定时任务，自动搜索芯片行业最新动态 → 对比分析 → 生成报告 → 微信推送。

| 文件 | 说明 |
|------|------|
| [auto_daily_update.py](auto_daily_update.py) | 每日自动更新脚本（GitHub Actions 8:30），搜索→LLM分析→HTML报告→微信推送 |
| [检索源清单.md](ipd_knowledge_base/检索源清单.md) | 定时检索源头，定义搜索范围和数据源 |
| [generate_report.py](ipd_knowledge_base/generate_report.py) | 报告生成器（手动模式），支持存量扫描和完整五步两种模式 |
| [output/](ipd_knowledge_base/output/) | 报告输出目录，包含 `index.html` + `push_log.txt` |

#### 报告结构

两种报告模式：

**自动模式**（`auto_daily_update.py`）：单页 HTML，含 3 个区块（增量信息 / 关键变化 / P0/P1 建议）

**手动模式**（`generate_report.py`）：5 个 Tab 标签页：

| Tab | 内容 | 说明 |
|-----|------|------|
| 概览 | Hero + 指标 + 执行摘要 | 主页面，简洁总结 |
| 检索源汇总 | 按 A-F 六类分组卡片 | 不含日期，含来源链接 |
| 建议 | P0/P1 优先级建议 | 步骤四产出 |
| 总结 | 行动要点 + P0 清单 | 步骤三四提炼 |
| 分析 | 关键变化（现象/原因/启示） | 步骤三产出 |

微信推送包含：主页概览 + 各分类汇总 + 来源链接 + P0 建议。
