"use strict";
const pptxgen = require("pptxgenjs");
const fs = require("fs");
const path = require("path");

// ── Language & path parameter ────────────────────────────────
// Usage: PPTX_LANGS=zh PPTX_BASE=data/output/energy node generate_pptx.js
const LANGS = (process.env.PPTX_LANGS || "zh,ja").split(",").map(s => s.trim());
const BASE = process.env.PPTX_BASE
  ? path.resolve(__dirname, process.env.PPTX_BASE)
  : path.join(__dirname, "data/output");

function getMissingRequiredFiles(lang) {
  const requiredFiles = [
    `A1_expected_scenarios_${lang}.json`,
    `C_used_in_D_${lang}.json`,
  ];
  return requiredFiles.filter(file => !fs.existsSync(path.join(BASE, file)));
}

function loadData(lang) {
  const a1Data = JSON.parse(fs.readFileSync(path.join(BASE, `A1_expected_scenarios_${lang}.json`), "utf-8"));
  const cData  = JSON.parse(fs.readFileSync(path.join(BASE, `C_used_in_D_${lang}.json`), "utf-8"));

  // Build title lookup: scenario_id → title (for translating references in D)
  const a1TitleMap = {}, cTitleMap = {};
  a1Data.forEach(d => { a1TitleMap[d.scenario_id] = d.title || ""; });
  cData.forEach(d => { cTitleMap[d.scenario_id] = d.title || ""; });

  let dData = [];
  try {
    dData = JSON.parse(fs.readFileSync(path.join(BASE, `D_opportunity_scenarios_${lang}.json`), "utf-8"));
    console.log(`[${lang}] Loaded ${dData.length} D scenarios`);
  } catch (e) {
    console.log(`[${lang}] D scenarios not found — skipping D pages`);
  }

  // Load signal title map for C source_signals
  let sigTitleMap = {};
  try { sigTitleMap = JSON.parse(fs.readFileSync(path.join(BASE, "signal_title_zh_map.json"), "utf-8")); } catch(e) {}

  // Enrich D references with translated titles
  dData.forEach(d => {
    (d.selected_expected || []).forEach(a => {
      if (a1TitleMap[a.id]) a.title = a1TitleMap[a.id];
    });
    (d.selected_unexpected || []).forEach(c => {
      if (cTitleMap[c.id]) c.title = cTitleMap[c.id];
    });
  });

  return { a1Data, cData, dData, sigTitleMap };
}

// Globals — reassigned per language in generateForLang()
let a1Data = [], cData = [], dData = [], sigTitleZh = {};
let a1IdMap = {}, cIdMap = {};
let currentLang = "zh";

// ── i18n labels ──────────────────────────────────────────────
const L = {
  zh: {
    pipelineTitle: "AI 情境分析管線",
    mvpReport: "MVP 成果報告",
    orgLine: "JRI × III Living Lab+",
    topicLine: "高齡社會情境 — 預期 ・ 非預期 ・ 機會情境",
    overview: "成果總覽",
    expected: "預期情境 Expected",
    expectedSub: "不可逆結構性變化",
    unexpected: "非預期情境 Unexpected",
    unexpectedSub: "弱信號驅動意外變局",
    opportunity: "機會情境 Opportunity",
    opportunitySub: "A × C 碰撞合成",
    flowTitle: "分析流程",
    flowTrend: "趨勢文獻",
    flowA: "A 預期情境",
    flowB: "B 弱信號",
    flowBSub: "1000筆",
    flowC: "C 非預期情境",
    flowD: "D 機會情境",
    flowPending: "待產出",
    flowDesc: "本報告透過 AI 情境分析管線，以 JRI 弱信號資料庫與高齡化趨勢文獻為輸入，系統性產出三類情境。" +
      "預期情境（A）描述不可逆的結構性變化；非預期情境（C）揭示弱信號驅動的意外變局；" +
      "機會情境（D）為 A × C 碰撞所產生的策略機會。每個情境附品質評分。",
    scoreLegendTitle: "評分維度說明",
    aLegend: [["Structural Depth", "結構分析深度"], ["Irreversibility", "不可逆程度"], ["Relevance", "相關性（合併）"], ["Feasibility", "可行性"]],
    cLegend: [["Unexpectedness", "意外程度"], ["Social Impact", "社會衝擊"], ["Uncertainty", "不確定性"]],
    dLegend: [["Unexpected", "意外程度"], ["Impact", "產業衝擊"], ["Plausibility", "可信度"]],
    changeFrom: "現況（Change from）",
    changeTo: "未來（To）",
    evidence: "佐證資料（Supporting Evidences）",
    postChange: "變化後情境（Post-Change Scenario）",
    implicationsA: "企業影響（Implications for the Company）",
    collisionInsight: "碰撞洞察",
    selectedExpected: "引用的預期情境（Selected Expected）",
    selectedUnexpected: "引用的非預期情境（Selected Unexpected）",
    background: "背景（Background）",
    aboutFuture: "關於未來（About the Future）",
    implicationsD: "企業影響（Implications for the Company）",
    approach: "具體行動方案（Company's Approach）",
    transformation: "轉型關鍵（Points for Transformation）",
    thankYou: "Thank You",
    endOrg: "JRI × III Living Lab+",
    endDPending: "D 類機會情境 — 待後續更新",
    noteOrigId: "原始編號",
    noteFrom: "現況 Change From",
    noteTo: "未來展望 Change To",
    noteCollision: "碰撞洞察",
    unit: "個",
    articles: "篇",
    opportunity_label: "[機會]",
    challenge_label: "[挑戰]",
  },
  ja: {
    pipelineTitle: "AI シナリオ分析パイプライン",
    mvpReport: "MVP 成果報告",
    orgLine: "JRI × III Living Lab+",
    topicLine: "高齢社会シナリオ — 予想 ・ 予想外 ・ 機会",
    overview: "成果概要",
    expected: "予想シナリオ Expected",
    expectedSub: "不可逆的な構造変化",
    unexpected: "予想外シナリオ Unexpected",
    unexpectedSub: "弱いシグナルが駆動する変局",
    opportunity: "機会シナリオ Opportunity",
    opportunitySub: "A × C 衝突合成",
    flowTitle: "分析フロー",
    flowTrend: "トレンド文献",
    flowA: "A 予想シナリオ",
    flowB: "B 弱いシグナル",
    flowBSub: "1000件",
    flowC: "C 予想外シナリオ",
    flowD: "D 機会シナリオ",
    flowPending: "作成中",
    flowDesc: "本レポートはAIシナリオ分析パイプラインにより、JRI弱信号データベースと高齢化トレンド文献を入力として、3種類のシナリオを体系的に生成。" +
      "予想シナリオ（A）は不可逆的な構造変化を記述。予想外シナリオ（C）は弱いシグナルが駆動する意外な変局を明示。" +
      "機会シナリオ（D）はA × Cの衝突から生まれる戦略的機会。各シナリオに品質スコアを付与。",
    scoreLegendTitle: "スコア次元の説明",
    aLegend: [["Structural Depth", "構造分析の深さ"], ["Irreversibility", "不可逆性"], ["Relevance", "関連性（統合）"], ["Feasibility", "実現可能性"]],
    cLegend: [["Unexpectedness", "意外性"], ["Social Impact", "社会的インパクト"], ["Uncertainty", "不確実性"]],
    dLegend: [["Unexpected", "意外性"], ["Impact", "産業インパクト"], ["Plausibility", "妥当性"]],
    changeFrom: "現状（Change from）",
    changeTo: "将来（To）",
    evidence: "裏付け資料（Supporting Evidences）",
    postChange: "変化後のシナリオ（Post-Change Scenario）",
    implicationsA: "企業への影響（Implications for the Company）",
    collisionInsight: "衝突インサイト",
    selectedExpected: "引用した予想シナリオ（Selected Expected）",
    selectedUnexpected: "引用した予想外シナリオ（Selected Unexpected）",
    background: "背景（Background）",
    aboutFuture: "将来について（About the Future）",
    implicationsD: "企業への影響（Implications for the Company）",
    approach: "具体的行動方策（Company's Approach）",
    transformation: "変革のポイント（Points for Transformation）",
    thankYou: "Thank You",
    endOrg: "JRI × III Living Lab+",
    endDPending: "D 機会シナリオ — 今後更新予定",
    noteOrigId: "元の番号",
    noteFrom: "現状 Change From",
    noteTo: "将来展望 Change To",
    noteCollision: "衝突インサイト",
    unit: "件",
    articles: "件",
    opportunity_label: "[機会]",
    challenge_label: "[課題]",
  },
};
function l(key) { return (L[currentLang] || L.zh)[key] || L.zh[key] || key; }

// ── Presentation Setup (reassigned per language) ──────────────
let pres = null;

// ── Palette ───────────────────────────────────────────────────
const C = {
  navy: "0F3460", teal: "1A7F8E", tealMid: "B8DDE6", white: "FFFFFF",
  text: "1E293B", textMid: "475569", textLight: "94A3B8",
  divider: "E2E8F0", cardBg: "F8FAFC",
  sA: "1A5276", sAL: "D4E6F1",
  sC: "7D3C98", sCL: "E8DAEF",
  sD: "B9770E", sDL: "FEF9E7",
  sDMain: "C0392B", sDLight: "FADBD8", sDBg: "FDEDEC",
  sDOrange: "D35400",
  scoreHi: "059669", scoreMd: "D97706", scoreLo: "94A3B8",
  evBg: "F7F9FB", impBg: "FDF8F0",
  imgBg: "F0F2F5",
};
const F = "Calibri";
let FZ = "Microsoft JhengHei";

// ── Page Counter (reassigned per language) ────────────────────
let totalPages = 0;
let pg = 0;

// ── Helpers ───────────────────────────────────────────────────
function t(v) {
  if (!v && v !== 0) return "";
  if (Array.isArray(v)) return v.join("\n").replace(/\\n/g, "\n").trim();
  return String(v).replace(/\\n/g, "\n").trim();
}
function tArr(v, sep) {
  if (!v) return "";
  if (Array.isArray(v)) return v.join(sep || " / ");
  return String(v);
}
function sc(s, max) {
  const pct = max ? s / max : s / 30;
  return pct >= 0.75 ? C.scoreHi : pct >= 0.55 ? C.scoreMd : C.scoreLo;
}

function estH(text, widthInches, fontSize) {
  const txt = t(text);
  if (!txt) return 0.15;
  const charW = currentLang === "en" ? 0.007 : 0.014;
  const charsPerLine = Math.floor(widthInches / (fontSize * charW));
  const lines = Math.ceil(txt.length / Math.max(charsPerLine, 1));
  return Math.max(0.2, lines * fontSize * 0.019 + 0.05);
}

function formatSourceSignals(signals) {
  if (!signals || !signals.length) return "";
  if (Array.isArray(signals)) {
    return signals.map(s => {
      if (typeof s === "object") {
        const id = s.signal_id || "";
        const title = t(s.title || "");
        return id ? `${id}: ${title}` : null;
      }
      const id = (String(s).match(/\d+/) || [])[0];
      return id ? `#${id}` : null;
    }).filter(Boolean).join("  ·  ");
  }
  return String(signals).trim();
}

function capItems(items, maxChars) {
  const txt = Array.isArray(items) ? items.join("\n") : t(items);
  return txt.length > maxChars ? txt.slice(0, maxChars) + "…" : txt;
}

function impPrefixColor(prefix) {
  if (/機會|機会|正面|收益|機遇|Opportunity/i.test(prefix)) return C.scoreHi;
  if (/風險|課題|リスク|注意|威脅|挑戰|Challenge/i.test(prefix)) return C.scoreMd;
  return C.textMid;
}
function localizeImpLabel(str) {
  return str.replace(/\[Opportunity\]/gi, l("opportunity_label")).replace(/\[Challenge\]/gi, l("challenge_label"));
}
function addImplications(slide, items, x, y, w, h, fs) {
  if (!items || !items.length) return;
  const sz = fs || 7.5;
  const runs = [];
  items.forEach((item, i) => {
    const str = localizeImpLabel(t(item));
    if (i > 0) runs.push({ text: "\n", options: { fontSize: sz, fontFace: FZ } });
    // Detect double-bracket: [Opportunity][Industry] body  or  [Challenge][Industry] body
    const dblM = str.match(/^\[([^\]]+)\]\[([^\]]+)\]\s*(.*)/s);
    if (dblM) {
      const typeColor = impPrefixColor(dblM[1]);
      runs.push({ text: `[${dblM[1]}]`, options: { bold: true, color: typeColor, fontSize: sz, fontFace: FZ } });
      runs.push({ text: `[${dblM[2]}] `, options: { bold: true, color: C.navy, fontSize: sz, fontFace: FZ } });
      runs.push({ text: dblM[3], options: { color: C.textMid, fontSize: sz, fontFace: FZ } });
    }
    // Detect single bracket [Opportunity] body  (backward compat)
    else {
      const sglM = str.match(/^\[([^\]]+)\]\s*(.*)/s);
      if (sglM) {
        const typeColor = impPrefixColor(sglM[1]);
        runs.push({ text: `[${sglM[1]}] `, options: { bold: true, color: typeColor, fontSize: sz, fontFace: FZ } });
        runs.push({ text: sglM[2], options: { color: C.textMid, fontSize: sz, fontFace: FZ } });
      }
      // Detect full-width bracket 【...】
      else {
        const bracketM = str.match(/^(【[^】]+】)(.*)/s);
        if (bracketM) {
          const color = impPrefixColor(bracketM[1]);
          runs.push({ text: bracketM[1], options: { bold: true, color, fontSize: sz, fontFace: FZ } });
          runs.push({ text: bracketM[2], options: { color: C.textMid, fontSize: sz, fontFace: FZ } });
        } else {
          runs.push({ text: str, options: { color: C.textMid, fontSize: sz, fontFace: FZ } });
        }
      }
    }
  });
  slide.addText(runs, { x, y, w, h, lineSpacingMultiple: 1.35, valign: "top", margin: 0 });
}

function addCompanyApproach(slide, items, x, y, w, h, fs) {
  if (!items || !items.length) return;
  const sz = fs || 7.5;
  const runs = [];
  items.forEach((item, i) => {
    let str = t(item);
    if (i > 0) runs.push({ text: "\n", options: { fontSize: sz, fontFace: FZ } });
    // Extract [Industry] tag if present (e.g., "1. [建設] **Title**: body")
    const indM = str.match(/^(\d+\.\s*)\[([^\]]+)\]\s*(.*)/s);
    if (indM) {
      runs.push({ text: indM[1], options: { bold: true, color: C.text, fontSize: sz, fontFace: FZ } });
      runs.push({ text: `[${indM[2]}] `, options: { bold: true, color: C.navy, fontSize: sz, fontFace: FZ } });
      str = indM[3];
    }
    // Parse **bold** markers in remaining text
    const parts = str.split(/\*\*(.*?)\*\*/g);
    parts.forEach((p, j) => {
      if (!p) return;
      if (j % 2 === 1) {
        runs.push({ text: p, options: { bold: true, color: C.text, fontSize: sz, fontFace: FZ } });
      } else {
        runs.push({ text: p, options: { color: C.textMid, fontSize: sz, fontFace: FZ } });
      }
    });
  });
  slide.addText(runs, { x, y, w, h, lineSpacingMultiple: 1.4, valign: "top", margin: 0 });
}

function addTransformationPoints(slide, items, x, y, w, h, fs) {
  if (!items || !items.length) return;
  const sz = fs || 7.5;
  const runs = [];
  items.forEach((item, i) => {
    const str = t(item);
    if (i > 0) runs.push({ text: "\n", options: { fontSize: sz, fontFace: FZ } });
    // Extract [Industry] tag if present (e.g., "[建設] Area: description")
    const indM = str.match(/^\[([^\]]+)\]\s*(.*)/s);
    if (indM) {
      runs.push({ text: `[${indM[1]}] `, options: { bold: true, color: C.navy, fontSize: sz, fontFace: FZ } });
      runs.push({ text: indM[2], options: { color: C.textMid, fontSize: sz, fontFace: FZ } });
    } else {
      runs.push({ text: "• " + str, options: { color: C.textMid, fontSize: sz, fontFace: FZ } });
    }
  });
  slide.addText(runs, { x, y, w, h, lineSpacingMultiple: 1.35, valign: "top", margin: 0 });
}

function pgNum(_slide) { pg++; }
function topBar(slide, color) {
  slide.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.03, fill: { color } });
}
function badge(slide, id, color, x, y) {
  slide.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.52, h: 0.24, fill: { color } });
  slide.addText(id, { x, y, w: 0.52, h: 0.24, fontSize: 8, bold: true, color: C.white, fontFace: F, align: "center", valign: "middle", margin: 0 });
}
function scoreLine(slide, d, x, y) {
  const q = d.total_score || 0;
  slide.addText(`${q}`, { x, y, w: 0.3, h: 0.24, fontSize: 9.5, bold: true, color: sc(q, 30), fontFace: F, margin: 0, valign: "middle" });
  if (d.score_structural_depth !== undefined) {
    [["Depth", d.score_structural_depth], ["Irrev.", d.score_irreversibility], ["Ind.", d.score_industry_related], ["Topic", d.score_topic_relevance], ["Feas.", d.score_feasibility]].forEach(([l, v], i) => {
      slide.addText(`${l} ${v}`, { x: x + 0.33 + i * 0.45, y, w: 0.43, h: 0.24, fontSize: 6.5, color: C.textLight, fontFace: F, margin: 0, valign: "middle" });
    });
  }
}
function pageTag(slide, label, color) {
  slide.addShape(pres.shapes.RECTANGLE, { x: 9.302, y: 0.15, w: 0.42, h: 0.236, fill: { color } });
  slide.addText(label, { x: 9.302, y: 0.15, w: 0.42, h: 0.236, fontSize: 6.5, bold: true, color: C.white, fontFace: F, align: "center", valign: "middle", margin: 0 });
}
function divLine(slide, y) {
  slide.addShape(pres.shapes.LINE, { x: 0.278, y, w: 9.444, h: 0, line: { color: C.divider, width: 0.6 } });
}
function secLabel(slide, text, color, x, y) {
  slide.addText(text, { x, y, w: 4, h: 0.2, fontSize: 8.5, bold: true, color, fontFace: FZ, margin: 0 });
}
function bodyTxt(slide, text, x, y, w, h, opts) {
  const defaults = { fontSize: 7, color: C.textMid, fontFace: FZ, margin: 0, lineSpacingMultiple: 1.35, valign: "top", shrinkText: true };
  slide.addText(t(text), { x, y, w, h, ...defaults, ...opts });
}
function noteBar(slide, text, bgColor, textColor, y) {
  if (!t(text)) return;
  slide.addShape(pres.shapes.RECTANGLE, { x: 0.278, y, w: 9.444, h: 0.27, fill: { color: bgColor } });
  slide.addText(t(text), { x: 0.389, y, w: 9.222, h: 0.27, fontSize: 6.5, color: textColor, fontFace: FZ, margin: 0, valign: "middle" });
}
function slide_card(s, x, y, w, h, borderColor, bgColor) {
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: bgColor || C.cardBg } });
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h: 0.035, fill: { color: borderColor } });
}

// ── TITLE SLIDE ───────────────────────────────────────────────
function titleSlide() {
  const s = pres.addSlide(); s.background = { color: C.navy };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.05, fill: { color: C.teal } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 5.575, w: 10, h: 0.05, fill: { color: C.teal } });
  s.addShape(pres.shapes.OVAL, { x: 7.5, y: -1, w: 4, h: 4, fill: { color: C.teal, transparency: 90 }, line: { color: C.teal, width: 0.5, transparency: 70 } });
  s.addText(l("pipelineTitle"), { x: 0.8, y: 1.4, w: 8.4, h: 0.8, fontSize: 38, bold: true, color: C.white, fontFace: FZ, margin: 0 });
  s.addText(l("mvpReport"), { x: 0.8, y: 2.15, w: 8.4, h: 0.6, fontSize: 28, color: C.tealMid, fontFace: FZ, margin: 0 });
  s.addShape(pres.shapes.LINE, { x: 0.8, y: 2.95, w: 2.5, h: 0, line: { color: C.teal, width: 2 } });
  s.addText([
    { text: l("orgLine"), options: { fontSize: 14, color: C.tealMid, breakLine: true } },
    { text: l("topicLine"), options: { fontSize: 12, color: C.textLight } },
  ], { x: 0.8, y: 3.2, w: 8.4, h: 0.85, fontFace: FZ, margin: 0, lineSpacingMultiple: 1.5 });
  s.addText("2026.03", { x: 0.8, y: 4.85, w: 3, h: 0.3, fontSize: 11, color: C.textLight, fontFace: F });
  pg++;
}

// ── OVERVIEW SLIDE ────────────────────────────────────────────
function overviewSlide() {
  const s = pres.addSlide(); s.background = { color: C.white }; topBar(s, C.teal);
  s.addText(l("overview"), { x: 0.6, y: 0.25, w: 8.8, h: 0.45, fontSize: 22, bold: true, color: C.text, fontFace: FZ, margin: 0 });
  divLine(s, 0.72);

  const dCount = dData.length > 0 ? String(dData.length) : "—";
  const stats = [
    { n: String(a1Data.length), label: l("expected"), sub: l("expectedSub"), c: C.sA, bg: C.sAL },
    { n: String(cData.length),  label: l("unexpected"), sub: l("unexpectedSub"), c: C.sC, bg: C.sCL },
    { n: dCount, label: l("opportunity"), sub: l("opportunitySub"), c: C.sDMain, bg: C.sDBg },
  ];
  stats.forEach((st, i) => {
    const x = 0.6 + i * 3.1;
    slide_card(s, x, 0.9, 2.85, 1.3, st.c, st.bg);
    s.addText(st.n, { x: x + 0.2, y: 0.96, w: 2.4, h: 0.6, fontSize: 38, bold: true, color: st.c, fontFace: F, margin: 0 });
    s.addText(st.label, { x: x + 0.2, y: 1.55, w: 2.4, h: 0.26, fontSize: 9.5, color: C.textMid, fontFace: FZ, margin: 0 });
    s.addText(st.sub, { x: x + 0.2, y: 1.8, w: 2.4, h: 0.22, fontSize: 8, color: st.c, fontFace: FZ, margin: 0 });
  });

  s.addText(l("flowTitle"), { x: 0.6, y: 2.4, w: 3, h: 0.28, fontSize: 11, bold: true, color: C.teal, fontFace: FZ, margin: 0 });
  const sp = currentLang === "en" ? " " : "";
  const dSub = dData.length > 0 ? `${dData.length}${sp}${l("unit")}`.trim() : l("flowPending");
  const steps = [
    { label: l("flowTrend"), sub: `${a1Data.length * 10}+${sp}${l("articles")}`, c: C.sA },
    null,
    { label: l("flowA"), sub: `${a1Data.length}${sp}${l("unit")}`.trim(), c: C.sA },
    "+",
    { label: l("flowB"), sub: l("flowBSub"), c: C.sC },
    null,
    { label: l("flowC"), sub: `${cData.length}${sp}${l("unit")}`.trim(), c: C.sC },
    null,
    { label: l("flowD"), sub: dSub, c: C.sDMain },
  ];
  let fx = 0.6;
  steps.forEach(st => {
    if (st === null) {
      s.addText("→", { x: fx, y: 2.78, w: 0.28, h: 0.38, fontSize: 13, color: C.textLight, fontFace: F, align: "center", valign: "middle", margin: 0 });
      fx += 0.28;
    } else if (typeof st === "string") {
      s.addText(st, { x: fx, y: 2.78, w: 0.28, h: 0.38, fontSize: 13, color: C.textLight, fontFace: F, align: "center", valign: "middle", margin: 0 });
      fx += 0.28;
    } else {
      const w = 1.1;
      s.addShape(pres.shapes.RECTANGLE, { x: fx, y: 2.78, w, h: 0.38, fill: { color: st.c } });
      s.addText(st.label, { x: fx, y: 2.78, w, h: 0.23, fontSize: 7.5, bold: true, color: C.white, fontFace: FZ, align: "center", valign: "middle", margin: 0 });
      if (st.sub) s.addText(st.sub, { x: fx, y: 2.98, w, h: 0.16, fontSize: 6.5, color: C.white, fontFace: FZ, align: "center", margin: 0, transparency: 30 });
      fx += w + 0.04;
    }
  });

  s.addText(l("flowDesc"),
    { x: 0.6, y: 3.35, w: 8.8, h: 0.65, fontSize: 9, color: C.textMid, fontFace: FZ, margin: 0, lineSpacingMultiple: 1.5 }
  );

  // Scoring dimension legend per scenario type
  s.addText(l("scoreLegendTitle"), { x: 0.6, y: 4.0, w: 3, h: 0.22, fontSize: 9, bold: true, color: C.teal, fontFace: FZ, margin: 0 });
  const legends = [
    ["A", l("aLegend")],
    ["C", l("cLegend")],
    ["D", l("dLegend")],
  ];
  legends.forEach(([type, dims], ri) => {
    const ly = 4.25 + ri * 0.24;
    s.addText(type + ":", { x: 0.6, y: ly, w: 0.3, h: 0.2, fontSize: 7.5, bold: true, color: C.text, fontFace: F, margin: 0 });
    const colW = 8.7 / dims.length;
    dims.forEach(([en, local], di) => {
      s.addText(`${en} (${local})`, { x: 0.9 + di * colW, y: ly, w: colW - 0.05, h: 0.2, fontSize: 6.5, color: C.textMid, fontFace: FZ, margin: 0 });
    });
  });

  pgNum(s);
}

// ── SECTION DIVIDER ───────────────────────────────────────────
function sectionDivider(title, subtitle, color, count) {
  const s = pres.addSlide(); s.background = { color: C.white };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 3.8, h: 5.625, fill: { color } });
  s.addText(String(count), { x: 0.3, y: 1.0, w: 3.2, h: 1.6, fontSize: 72, bold: true, color: C.white, fontFace: F, margin: 0, transparency: 20 });
  s.addText(currentLang === "ja" ? "シナリオ" : currentLang === "zh" ? "個情境" : "Scenarios", { x: 0.3, y: 2.5, w: 3.2, h: 0.5, fontSize: 16, color: C.white, fontFace: FZ, margin: 0, transparency: 10 });
  s.addText(title, { x: 4.4, y: 1.6, w: 5.2, h: 1.0, fontSize: 30, bold: true, color: C.text, fontFace: FZ, margin: 0 });
  s.addShape(pres.shapes.LINE, { x: 4.4, y: 2.7, w: 2, h: 0, line: { color, width: 2.5 } });
  s.addText(subtitle, { x: 4.4, y: 2.9, w: 5.2, h: 1.0, fontSize: 11, color: C.textMid, fontFace: FZ, margin: 0, lineSpacingMultiple: 1.6 });
  pg++;
}

// ── Extract subject (topic) from title for display heading ────
// e.g. "高齡者的移動方式從「私家車」轉向「多層式智慧移動網」" → "高齡者的移動方式"
function extractSubjectTitle(title) {
  if (currentLang === "en") {
    const m = title.match(/^(.+?)(?=\s+(?:will|shift|transform|move|transition|from\s+"))/i);
    return m ? m[1].trim() : title.slice(0, 40);
  }
  const m = title.match(/^(.+?)(?=將轉為|將從|轉向|走向|轉變為|轉為「)/) ||
            title.match(/^(.+?)從「/);
  return m ? m[1].trim() : title.slice(0, 18);
}

// ── Extract FROM/TO keywords from title brackets ──────────────
function extractKeywords(title) {
  if (currentLang === "en") {
    // English: look for "from X to Y" or quoted terms
    const fromTo = title.match(/from\s+"([^"]+)"\s+to\s+"([^"]+)"/i);
    if (fromTo) return { from: fromTo[1], to: fromTo[2] };
    const quotes = (title.match(/"([^"]+)"/g) || []).map(q => q.replace(/"/g, ''));
    if (quotes.length >= 2) return { from: quotes[0], to: quotes[1] };
    return { from: title.slice(0, 30), to: title.slice(-30) };
  }
  const brackets = (title.match(/「([^」]+)」/g) || []).map(b => b.replace(/[「」]/g, ''));
  if (brackets.length >= 2) return { from: brackets[0], to: brackets[1] };
  if (brackets.length === 1) {
    const m = title.match(/^(.+?)(?=將轉為|轉向|走向|轉變為|轉為「)/);
    return { from: m ? m[1].trim() : title.slice(0, 12), to: brackets[0] };
  }
  return { from: title.slice(0, 14), to: title.slice(-14) };
}
function kwFontSize(kw) {
  const len = kw.length;
  if (currentLang === "en") {
    if (len <= 12) return 22;
    if (len <= 20) return 18;
    if (len <= 35) return 14;
    if (len <= 50) return 11;
    return 9;
  }
  if (len <= 5)  return 26;
  if (len <= 8)  return 22;
  if (len <= 12) return 18;
  if (len <= 18) return 14;
  return 11;
}

// ── A1 PAGE 1 (JRI reference layout: big FROM→TO + evidence/post-change + implications) ──
function a1P1(d, displayIdx) {
  const s = pres.addSlide(); s.background = { color: C.white }; topBar(s, C.sA);
  const displayId = String(displayIdx);
  badge(s, displayId, C.sA, 0.278, 0.15);
  const q = d.total_score || 0;
  const scoreA = `${q}/50  |  Depth ${d.score_structural_depth||0}  Irreversib. ${d.score_irreversibility||0}  Ind. ${d.score_industry_related||0}  Topic ${d.score_topic_relevance||0}  Feas. ${d.score_feasibility||0}`;
  s.addText(scoreA, { x: 3.5, y: 0.15, w: 6.222, h: 0.24, fontSize: 8, color: "A0A0A0", fontFace: F, align: "right", valign: "middle", margin: 0 });

  // Title — full title
  const displayTitle = t(d.title);
  s.addText(displayTitle, { x: 0.278, y: 0.417, w: 9.444, h: 0.458, fontSize: 22, bold: true, color: C.text, fontFace: FZ, margin: 0, valign: "middle", shrinkText: true });
  divLine(s, 0.917);

  // ── FROM / TO upper two boxes ──────────────────────────────
  const KW_Y = 0.972, KW_H = 1.042;
  const LX = 0.278, leftW = 4.444, arrowW = 0.333, rightX = 5.056, rightW = 4.667;

  // Change From box (left)
  s.addShape(pres.shapes.RECTANGLE, { x: LX, y: KW_Y, w: leftW, h: KW_H, fill: { color: C.cardBg } });
  s.addShape(pres.shapes.RECTANGLE, { x: LX, y: KW_Y, w: leftW, h: 0.028, fill: { color: C.sA } });
  s.addText(l("changeFrom"), { x: 0.389, y: 1.028, w: 4.222, h: 0.194, fontSize: 9, color: C.textLight, fontFace: FZ, margin: 0 });
  s.addText(t(d.change_from_keyword) || extractKeywords(t(d.title)).from, {
    x: 0.389, y: 1.25, w: 4.222, h: 0.722,
    fontSize: kwFontSize(t(d.change_from_keyword) || extractKeywords(t(d.title)).from),
    bold: true, color: C.sA, fontFace: FZ, margin: 0, lineSpacingMultiple: 1.2, valign: "top", wrap: true, shrinkText: true,
  });

  // Arrow
  s.addText("→", { x: 4.722, y: KW_Y, w: arrowW, h: KW_H, fontSize: 26, bold: true, color: C.textLight, fontFace: F, align: "center", valign: "middle", margin: 0 });

  // Change To box (right)
  s.addShape(pres.shapes.RECTANGLE, { x: rightX, y: KW_Y, w: rightW, h: KW_H, fill: { color: "EBF5FB" } });
  s.addShape(pres.shapes.RECTANGLE, { x: rightX, y: KW_Y, w: rightW, h: 0.028, fill: { color: C.teal } });
  s.addText(l("changeTo"), { x: 5.167, y: 1.028, w: 4.444, h: 0.194, fontSize: 9, color: C.textLight, fontFace: FZ, margin: 0 });
  s.addText(t(d.change_to_keyword) || extractKeywords(t(d.title)).to, {
    x: 5.167, y: 1.25, w: 4.444, h: 0.722,
    fontSize: kwFontSize(t(d.change_to_keyword) || extractKeywords(t(d.title)).to),
    bold: true, color: C.teal, fontFace: FZ, margin: 0, lineSpacingMultiple: 1.2, valign: "top", wrap: true, shrinkText: true,
  });

  // ── Middle divider ──────────────────────────────────────────
  divLine(s, 2.069);
  s.addText(l("evidence"), { x: 0.389, y: 2.125, w: 4.236, h: 0.194, fontSize: 8.5, bold: true, color: C.sA, fontFace: FZ, margin: 0 });
  s.addText(l("postChange"), { x: 5.056, y: 2.125, w: 4.722, h: 0.194, fontSize: 8.5, bold: true, color: C.teal, fontFace: FZ, margin: 0 });

  // ── Lower two boxes (evidence left / post-change right) ─────
  const evItems = Array.isArray(d.supporting_evidences) ? d.supporting_evidences : [];
  const evText  = evItems.map((e, i) => `${i + 1}. ${e}`).join("\n");
  const pcText  = t(d.post_change_scenario);

  // Left: Supporting Evidences
  s.addShape(pres.shapes.RECTANGLE, { x: 0.278, y: 2.319, w: 4.444, h: 1.778, fill: { color: C.evBg } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.278, y: 2.319, w: 0.028, h: 1.778, fill: { color: C.sA } });
  bodyTxt(s, evText, 0.389, 2.361, 4.222, 1.694, { fontSize: 8, lineSpacingMultiple: 1.4 });

  // Right: Post-Change Scenario
  s.addShape(pres.shapes.RECTANGLE, { x: 5.056, y: 2.319, w: 4.667, h: 1.778, fill: { color: "F0F9FF" } });
  s.addShape(pres.shapes.RECTANGLE, { x: 5.056, y: 2.319, w: 4.667, h: 0.028, fill: { color: C.teal } });
  bodyTxt(s, pcText, 5.167, 2.361, 4.444, 1.694, { fontSize: 8, lineSpacingMultiple: 1.4 });

  // ── Full-width Implications band (企業への影響) ───────────────
  const impItems = d.implications_for_company || [];
  s.addShape(pres.shapes.RECTANGLE, { x: 0.278, y: 4.167, w: 9.444, h: 1.25, fill: { color: C.impBg } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.278, y: 4.167, w: 9.444, h: 0.028, fill: { color: C.sDMain } });
  s.addText(l("implicationsA"), { x: 0.389, y: 4.208, w: 9.222, h: 0.194, fontSize: 9, bold: true, color: C.sDMain, fontFace: FZ, margin: 0 });
  addImplications(s, impItems, 0.389, 4.417, 9.222, 0.944, 8);

  // Speaker notes: original scenario_id + full change_from / change_to descriptions
  const noteLines = [`${l("noteOrigId")}: ${d.scenario_id}`];
  if (d.change_from) noteLines.push(`【${l("noteFrom")}】\n` + t(d.change_from));
  if (d.change_to)   noteLines.push(`【${l("noteTo")}】\n` + t(d.change_to));
  if (noteLines.length) s.addNotes(noteLines.join("\n\n"));

  pgNum(s);
}

// ── IMAGE PLACEHOLDER SLIDE (D only) ──────────────────────────
function imgSlide(d, color, tag, maxTag, titleKey, displayIdx) {
  const s = pres.addSlide(); s.background = { color: C.imgBg }; topBar(s, color);
  badge(s, String(displayIdx), color, 0.278, 0.15);
  pageTag(s, `${tag}/${maxTag}`, color);

  const rawTitle = t(d[titleKey] || "");
  const shortT = rawTitle.length > 55 ? rawTitle.slice(0, 55) + "…" : rawTitle;
  s.addText(shortT, { x: 1.05, y: 0.15, w: 7.8, h: 0.24, fontSize: 8, color: C.textMid, fontFace: FZ, margin: 0, valign: "middle" });
  divLine(s, 0.42);

  // Large image placeholder box
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 0.55, w: 8.6, h: 4.38,
    fill: { color: C.white },
    line: { color: "CCCCCC", width: 1.5, dashType: "lgDash" },
  });
  const imgPlaceholder = currentLang === "ja" ? "[ シナリオ視覚化画像 ]" : currentLang === "zh" ? "[ 情境視覺化圖片 ]" : "[ Scenario Visualization Image ]";
  const imgNote = currentLang === "ja" ? "このページはシナリオ視覚化画像用に確保されています。実際の画像に差し替えてください" : currentLang === "zh" ? "此頁保留供情境視覺化圖片使用，請置換為實際圖片" : "This page is reserved for a scenario visualization image. Replace with the actual image.";
  s.addText(imgPlaceholder, {
    x: 0.7, y: 0.55, w: 8.6, h: 4.38,
    fontSize: 14, color: "BBBBBB", fontFace: FZ,
    align: "center", valign: "middle", margin: 0,
  });

  s.addText(imgNote, {
    x: 0.7, y: 4.98, w: 8.6, h: 0.22,
    fontSize: 7, color: C.textLight, fontFace: FZ,
    align: "center", margin: 0,
  });

  // Speaker notes: original scenario_id
  s.addNotes(`${l("noteOrigId")}: ${d.scenario_id}`);

  pgNum(s);
}

// ── C PAGE 1: JRI vertical stacked layout ──────────────────────
// Left: labels (Overview/WHY/WHO/WHERE/WHAT-HOW) + timeline
// Right: content flowing vertically, dashed dividers between sections
function cP1(d, displayIdx) {
  const s = pres.addSlide(); s.background = { color: C.white }; topBar(s, C.sC);
  const displayId = String(displayIdx);
  badge(s, displayId, C.sC, 0.278, 0.15);

  // Decade badge
  const decadeLabel = d.timeline_decade || d.decade || "";
  if (decadeLabel) {
    s.addShape(pres.shapes.RECTANGLE, { x: 0.778, y: 0.15, w: 0.6, h: 0.236, fill: { color: C.sCL } });
    s.addText(decadeLabel, { x: 0.778, y: 0.15, w: 0.6, h: 0.236, fontSize: 8, bold: true, color: C.sC, fontFace: F, align: "center", valign: "middle", margin: 0 });
  }
  // Score — English labels
  const q = d.total_score || 0;
  const hasSubScores = d.score_unexpectedness !== undefined;
  const scoreStr = hasSubScores
    ? `${q}/30  |  Unexpect. ${d.score_unexpectedness||0}  Impact ${d.score_social_impact||0}  Uncert. ${d.score_uncertainty||0}`
    : `${q}/30`;
  s.addText(scoreStr, { x: 4.2, y: 0.15, w: 5.522, h: 0.24, fontSize: 8, color: "A0A0A0", fontFace: F, align: "right", valign: "middle", margin: 0 });

  // Title
  s.addText(t(d.title), { x: 0.278, y: 0.444, w: 9.444, h: 0.417, fontSize: 16, bold: true, color: C.text, fontFace: FZ, margin: 0, lineSpacingMultiple: 1.1, shrinkText: true });

  // ── Main table frame ──
  // Left label column: L:24, W:64 → x:0.333, w:0.889
  // Right content column: L:100, W:592 → x:1.389, w:8.222
  const LBL_X = 0.333, LBL_W = 0.889;
  const CNT_X = 1.389, CNT_W = 8.222;
  const FS = 8;

  // Outer border: L:20, T:65, W:680, H:300
  const BOX_Y = 0.903, BOX_H = 4.167;
  s.addShape(pres.shapes.RECTANGLE, { x: 0.278, y: BOX_Y, w: 9.444, h: BOX_H, fill: { color: C.white }, line: { color: C.sC, width: 1 } });
  // Vertical separator: L:92, T:65, W:0, H:300
  s.addShape(pres.shapes.LINE, { x: 1.278, y: BOX_Y, w: 0, h: BOX_H, line: { color: C.sC, width: 0.5 } });

  // Horizontal dividers at T:147, 209, 241, 283
  [2.042, 2.903, 3.347, 3.931].forEach(dy => {
    s.addShape(pres.shapes.LINE, { x: 0.278, y: dy, w: 9.444, h: 0, line: { color: "BBBBBB", width: 0.5, dashType: "dash" } });
  });

  // Fixed-height row definitions: { label, key, y (pt/72), h (pt/72), hRight? }
  const rows = [
    { label: "Overview",   key: "overview",  y: 0.944, h: 1.056 },
    { label: "WHY",        key: "why",       y: 2.083, h: 0.778 },
    { label: "WHO",        key: "who",       y: 2.931, h: 0.375 },
    { label: "WHERE",      key: "where",     y: 3.389, h: 0.486 },
    { label: "WHAT/\nHOW", key: "what_how",  y: 3.958, h: 0.778, hRight: 1.056 },
  ];

  rows.forEach(row => {
    // Label (left column)
    s.addText(row.label, {
      x: LBL_X, y: row.y, w: LBL_W, h: row.h,
      fontSize: 9, bold: true, color: C.sC, fontFace: F, margin: 0,
      valign: "middle", align: "center", lineSpacingMultiple: 1.2,
    });

    // Content (right column)
    const rawData = d[row.key];
    let displayText = t(rawData);
    if (Array.isArray(rawData) && rawData.length > 1) {
      displayText = rawData.map(item => "■  " + t(item)).join("\n");
    } else if (Array.isArray(rawData) && rawData.length === 1) {
      displayText = t(rawData[0]);
    }

    const contentH = row.hRight || row.h;
    bodyTxt(s, displayText, CNT_X + 0.06, row.y, CNT_W - 0.12, contentH, {
      fontSize: FS, lineSpacingMultiple: 1.35,
    });
  });

  // ── Source signals — bottom bar ────
  // Bg: x:0.278, y:5.111, w:9.444, h:0.389
  // Color bar: x:0.278, y:5.111, w:9.444, h:0.028
  // Text: x:0.389, y:5.153
  const srcSignals = d.source_signals || [];
  if (srcSignals.length > 0) {
    const shown = srcSignals.slice(0, 5).map(sig => {
      if (typeof sig === "object") {
        const id = sig.signal_id || "";
        const localTitle = currentLang === "zh" ? (sig.title_zh || sigTitleZh[id] || sigTitleZh[String(id)] || "") : "";
        const title = localTitle || t(sig.title || "");
        const hasRealTitle = title && title !== id && !/^\d+$/.test(title.trim());
        return hasRealTitle ? `${id}: ${title}` : `#${id}`;
      }
      return String(sig);
    });
    const extra = srcSignals.length - shown.length;
    const srcY = 5.111;
    s.addShape(pres.shapes.RECTANGLE, { x: 0.278, y: srcY, w: 9.444, h: 0.389, fill: { color: "F9F5FF" } });
    s.addShape(pres.shapes.RECTANGLE, { x: 0.278, y: srcY, w: 9.444, h: 0.028, fill: { color: C.sC } });
    const srcRuns = [
      { text: (currentLang === "ja" ? "ソース弱信号  " : currentLang === "zh" ? "來源弱信號  " : "Source Weak Signals  "), options: { bold: true, color: C.sC, fontSize: 7, fontFace: FZ } },
    ];
    shown.forEach((txt, i) => {
      if (i > 0) srcRuns.push({ text: "  ·  ", options: { color: C.textLight, fontSize: 7, fontFace: FZ } });
      srcRuns.push({ text: txt, options: { color: C.textMid, fontSize: 7.5, fontFace: FZ } });
    });
    if (extra > 0) srcRuns.push({ text: `  (+${extra})`, options: { color: C.textLight, fontSize: 6, fontFace: FZ } });
    s.addText(srcRuns, { x: 0.389, y: 5.153, w: 9.222, h: 0.333, margin: 0, valign: "top", lineSpacingMultiple: 1.2 });
  }

  // Speaker notes: original scenario_id
  s.addNotes(`${l("noteOrigId")}: ${d.scenario_id}`);

  pgNum(s);
}

// ── D PAGE 1: JRI reference layout ──────────────────────────────
// Title → Collision Insight → Selected A (left) | Selected C (right) → Background (left) | About the Future (right)
function dP1(d, displayIdx) {
  const s = pres.addSlide(); s.background = { color: C.white }; topBar(s, C.sDMain);
  const displayId = String(displayIdx);
  badge(s, displayId, C.sDMain, 0.278, 0.15);

  const ts = d.total_score || 0;
  const scoreD = `${ts}/30  |  Unexpected ${d.unexpected_score||0}  Impact ${d.impact_score||0}  Plausib. ${d.plausibility_score||0}`;
  s.addText(scoreD, { x: 3.0, y: 0.15, w: 6.246, h: 0.24, fontSize: 7.5, color: "A0A0A0", fontFace: F, align: "right", valign: "middle", margin: 0 });
  pageTag(s, "1/3", C.sDMain);

  // ── Title: x:0.278, y:0.417, w:9.444, h:0.361 ──
  s.addText(t(d.opportunity_title), { x: 0.278, y: 0.417, w: 9.444, h: 0.361, fontSize: 16, bold: true, color: C.sDMain, fontFace: FZ, margin: 0, lineSpacingMultiple: 1.15, valign: "top", shrinkText: true });

  // ── Collision Insight (full-width highlight bar) ──
  // Bg: x:0.278, y:0.806, w:9.444, h:0.444
  // Left side bar: x:0.278, y:0.806, w:0.028, h:0.444
  // Label: x:0.389, y:0.833, w:9.222, h:0.167
  // Content: x:0.389, y:0.986, w:9.222, h:0.25
  let insText = t(d.collision_insight);
  // Replace original scenario IDs (e.g. A-3, C-15) with presentation display IDs
  insText = insText.replace(/A-(\d+)/g, (_, n) => `A${a1IdMap["A-" + n] || n}`);
  insText = insText.replace(/C-(\d+)/g, (_, n) => `C${cIdMap["C-" + n] || n}`);
  s.addShape(pres.shapes.RECTANGLE, { x: 0.278, y: 0.806, w: 9.444, h: 0.444, fill: { color: C.sDBg } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.278, y: 0.806, w: 0.028, h: 0.444, fill: { color: C.sDMain } });
  s.addText(l("collisionInsight"), { x: 0.389, y: 0.833, w: 9.222, h: 0.167, fontSize: 7, bold: true, color: C.sDMain, fontFace: FZ, margin: 0 });
  bodyTxt(s, insText, 0.389, 0.986, 9.222, 0.25, { fontSize: 8, color: C.text, lineSpacingMultiple: 1.3 });

  // ══════════════════════════════════════════════════════════════
  // Upper two boxes (引用シナリオ)
  // Left box: x:0.278, y:1.292, w:4.722, h:0.917
  // Right box: x:5.056, y:1.292, w:4.667, h:0.917
  // ══════════════════════════════════════════════════════════════
  const ROW1_Y = 1.292, ROW1_H = 0.917;
  const L_W = 4.722, R_X = 5.056, R_W = 4.667;

  // Selected Expected Scenarios (A) — left
  s.addShape(pres.shapes.RECTANGLE, { x: 0.278, y: ROW1_Y, w: L_W, h: ROW1_H, fill: { color: C.white }, line: { color: "CCCCCC", width: 0.5 } });
  s.addText(l("selectedExpected"), { x: 0.389, y: ROW1_Y + 0.041, w: 4.5, h: 0.194, fontSize: 8, bold: true, color: C.text, fontFace: FZ, margin: 0 });
  const selAItems = d.selected_expected || [];
  const selAText = selAItems.map(a => {
    const title = t(a.title);
    const dispIdx = a1IdMap[a.id] || a.id || "";
    return `A${dispIdx}. ${title}`;
  }).join("\n");
  bodyTxt(s, selAText, 0.389, ROW1_Y + 0.264, 4.5, 0.611, { fontSize: 7, lineSpacingMultiple: 1.4 });

  // Selected Unexpected Scenarios (C) — right
  s.addShape(pres.shapes.RECTANGLE, { x: R_X, y: ROW1_Y, w: R_W, h: ROW1_H, fill: { color: C.white }, line: { color: "CCCCCC", width: 0.5 } });
  s.addText(l("selectedUnexpected"), { x: 5.167, y: ROW1_Y + 0.041, w: 4.444, h: 0.194, fontSize: 8, bold: true, color: C.text, fontFace: FZ, margin: 0 });
  const selCItems = d.selected_unexpected || [];
  const selCText = selCItems.map(c => {
    const title = t(c.title);
    const dispIdx = cIdMap[c.id] || c.id || "";
    return `C${dispIdx}. ${title}`;
  }).join("\n");
  bodyTxt(s, selCText, 5.167, ROW1_Y + 0.264, 4.444, 0.611, { fontSize: 7, lineSpacingMultiple: 1.4 });

  // ══════════════════════════════════════════════════════════════
  // Lower two boxes (背景 / 将来)
  // Left box: x:0.278, y:2.264, w:4.722, h:3.292
  // Right box: x:5.056, y:2.264, w:4.667, h:3.292
  // ══════════════════════════════════════════════════════════════
  const ROW2_Y = 2.264, ROW2_H = 3.292;

  // Background — left
  s.addShape(pres.shapes.RECTANGLE, { x: 0.278, y: ROW2_Y, w: L_W, h: ROW2_H, fill: { color: C.white }, line: { color: "CCCCCC", width: 0.5 } });
  s.addText(l("background"), { x: 0.389, y: ROW2_Y + 0.042, w: 4.5, h: 0.194, fontSize: 8.5, bold: true, color: C.text, fontFace: FZ, margin: 0 });
  bodyTxt(s, t(d.background), 0.389, ROW2_Y + 0.278, 4.5, 2.944, { fontSize: 8.5, lineSpacingMultiple: 1.4 });

  // About the Future — right
  s.addShape(pres.shapes.RECTANGLE, { x: R_X, y: ROW2_Y, w: R_W, h: ROW2_H, fill: { color: C.white }, line: { color: "CCCCCC", width: 0.5 } });
  s.addText(l("aboutFuture"), { x: 5.167, y: ROW2_Y + 0.042, w: 4.444, h: 0.194, fontSize: 8.5, bold: true, color: C.text, fontFace: FZ, margin: 0 });
  bodyTxt(s, t(d.about_the_future), 5.167, ROW2_Y + 0.278, 4.444, 2.944, { fontSize: 8.5, lineSpacingMultiple: 1.4 });

  // Speaker notes: original scenario_id + collision insight
  const dNotes = [`${l("noteOrigId")}: ${d.scenario_id}`];
  if (insText) dNotes.push(`【${l("noteCollision")}】\n` + insText);
  s.addNotes(dNotes.join("\n\n"));

  pgNum(s);
}

// ── Parse role_evolution item → { era, desc } ────────────────
function parseRoleItem(item, idx) {
  const str = typeof item === "object"
    ? ((item.era || "") + (item.description ? "：" + item.description : ""))
    : t(item);
  const m = str.match(/^(.{2,12}?)[：:](.+)$/s);
  if (m) return { era: m[1].trim(), desc: m[2].trim() };
  return { era: `Era ${idx + 1}`, desc: str };
}

// ── D PAGE 2: JRI reference layout ──────────────────────────────
// Left: Implications for the Company
// Right: Company's Approach and Measures
// Bottom full width: Points for Transformation
function dP2(d, displayIdx) {
  const s = pres.addSlide(); s.background = { color: C.white }; topBar(s, C.sDMain);
  badge(s, String(displayIdx), C.sDMain, 0.278, 0.15);
  pageTag(s, "2/3", C.sDMain);

  // Title text: x:1.056, y:0.153, w:7.806, h:0.375
  const rawT = t(d.opportunity_title);
  const shortT = rawT.length > 72 ? rawT.slice(0, 72) + "…" : rawT;
  s.addText(shortT, { x: 1.056, y: 0.153, w: 7.806, h: 0.375, fontSize: 8, color: C.textMid, fontFace: FZ, margin: 0, valign: "middle", lineSpacingMultiple: 1.1 });
  // Divider line: x:0.278, y:0.458, w:9.444
  divLine(s, 0.458);

  // Left/Right column titles: y:0.5, h:0.222
  // Left title:  x:0.278, w:4.861
  // Right title: x:5.194, w:4.528
  const FS = 7.5;

  // ══════════════════════════════════════════════════════════════
  // LEFT column title + content box
  // Left title:  x:0.278, y:0.5, w:4.861, h:0.222
  // Left bg:     x:0.278, y:0.722, w:4.861, h:4.167
  // Left bar:    x:0.278, y:0.722, w:4.861, h:0.028
  // Left text:   x:0.389, y:0.75,  w:4.639, h:4.097
  // ══════════════════════════════════════════════════════════════
  s.addText(l("implicationsD"), { x: 0.278, y: 0.5, w: 4.861, h: 0.222, fontSize: 9, bold: true, color: C.sDMain, fontFace: FZ, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.278, y: 0.722, w: 4.861, h: 4.167, fill: { color: C.impBg } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.278, y: 0.722, w: 4.861, h: 0.028, fill: { color: C.sDMain } });
  const impItems = d.implications_for_company || (d.company_perspective || {}).implications || [];
  addImplications(s, impItems, 0.389, 0.75, 4.639, 4.097, FS);

  // ══════════════════════════════════════════════════════════════
  // RIGHT column title + content box
  // Right title: x:5.194, y:0.5, w:4.528, h:0.222
  // Right bg:    x:5.194, y:0.722, w:4.528, h:4.167
  // Right text:  x:5.306, y:0.75,  w:4.306, h:4.097
  // ══════════════════════════════════════════════════════════════
  s.addText(l("approach"), { x: 5.194, y: 0.5, w: 4.528, h: 0.222, fontSize: 9, bold: true, color: C.sDMain, fontFace: FZ, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 5.194, y: 0.722, w: 4.528, h: 4.167, fill: { color: C.cardBg } });
  const appItems = d.company_approach || [];
  addCompanyApproach(s, appItems, 5.306, 0.75, 4.306, 4.097, FS);

  // ══════════════════════════════════════════════════════════════
  // BOTTOM: Points for Transformation (full width)
  // Divider: x:0.278, y:4.917, w:9.444
  // Title:   x:0.278, y:4.944, w:9.444, h:0.222
  // Bg:      x:0.278, y:5.181, w:9.444, h:0.361
  // Bar:     x:0.278, y:5.181, w:9.444, h:0.028
  // Text:    x:0.389, y:5.222, w:9.222, h:0.431
  // ══════════════════════════════════════════════════════════════
  divLine(s, 4.917);
  s.addText(l("transformation"), { x: 0.278, y: 4.944, w: 9.444, h: 0.222, fontSize: 9, bold: true, color: C.sDOrange, fontFace: FZ, margin: 0 });
  const transItems = d.transformation_points || [];
  if (transItems.length) {
    s.addShape(pres.shapes.RECTANGLE, { x: 0.278, y: 5.181, w: 9.444, h: 0.361, fill: { color: "FEF9E7" } });
    s.addShape(pres.shapes.RECTANGLE, { x: 0.278, y: 5.181, w: 9.444, h: 0.028, fill: { color: C.sDOrange } });
    addTransformationPoints(s, transItems, 0.389, 5.222, 9.222, 0.431, FS);
  }

  pgNum(s);
}

// ── END SLIDE ─────────────────────────────────────────────────
function endSlide() {
  const s = pres.addSlide(); s.background = { color: C.navy };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.04, fill: { color: C.teal } });
  s.addText(l("thankYou"), { x: 0.8, y: 1.8, w: 8.4, h: 0.8, fontSize: 36, bold: true, color: C.white, fontFace: F, margin: 0 });
  s.addShape(pres.shapes.LINE, { x: 0.8, y: 2.7, w: 2, h: 0, line: { color: C.teal, width: 2 } });
  s.addText(l("endOrg"), { x: 0.8, y: 2.9, w: 8.4, h: 0.5, fontSize: 14, color: C.tealMid, fontFace: FZ, margin: 0 });
  if (dData.length === 0) {
    s.addText(l("endDPending"), { x: 0.8, y: 3.5, w: 8.4, h: 0.4, fontSize: 11, color: C.textLight, fontFace: FZ, margin: 0 });
  }
  pg++;
}

// ── GENERATE (both zh and ja) ─────────────────────────────────
async function generateForLang(lang) {
  const missingFiles = getMissingRequiredFiles(lang);
  if (missingFiles.length > 0) {
    console.log(`\n[${lang}] Skipped: missing required input files: ${missingFiles.join(", ")}`);
    return false;
  }

  currentLang = lang;
  FZ = lang === "ja" ? "Meiryo" : lang === "zh" ? "Microsoft JhengHei" : "Calibri";
  const data = loadData(lang);
  // Update globals used by slide functions
  a1Data = data.a1Data;
  cData = data.cData;
  dData = data.dData;
  sigTitleZh = data.sigTitleMap;

  // Build scenario_id → display index maps
  a1IdMap = {}; a1Data.forEach((d, i) => { a1IdMap[d.scenario_id] = i + 1; });
  cIdMap = {};  cData.forEach((d, i) => { cIdMap[d.scenario_id] = i + 1; });

  totalPages =
    1 + 1 +
    1 + a1Data.length +
    1 + cData.length +
    (dData.length > 0 ? 1 + dData.length * 3 : 0) +
    1;
  pg = 0;

  pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.author = "III × JRI";
  pres.title = lang === "ja" ? "AI シナリオ分析パイプライン — MVP 成果報告" : lang === "zh" ? "AI 情境分析管線 — MVP 成果報告" : "AI Scenario Analysis Pipeline — MVP Results Report";

  console.log(`\n[${lang}] Generating ${totalPages} slides...`);
  console.log(`  A: ${a1Data.length} slides | C: ${cData.length} slides | D: ${dData.length} × 3 = ${dData.length * 3} slides`);

  titleSlide();
  overviewSlide();

  sectionDivider(
    lang === "ja" ? "予想シナリオ" : lang === "zh" ? "預期情境" : "Expected Scenarios",
    lang === "ja"
      ? "高齢社会トレンド分析に基づく不可逆的な構造変化。\n各シナリオは構造的深さ・不可逆性・産業関連性で評価。"
      : lang === "zh"
      ? "基於高齡社會趨勢分析的不可逆結構性變化。\n每個情境評估結構深度、不可逆性與產業相關性。"
      : "Irreversible structural changes based on aging society trend analysis.\nEach scenario is scored on structural depth, irreversibility, and industry relevance.",
    C.sA, a1Data.length
  );
  a1Data.forEach((d, i) => { a1P1(d, i + 1); });

  sectionDivider(
    lang === "ja" ? "予想外シナリオ" : lang === "zh" ? "非預期情境" : "Unexpected Scenarios",
    lang === "ja"
      ? "弱いシグナルが駆動する予想外の変局 — 従来の予測範囲外だが、\n大きな潜在的影響を持つシナリオの可能性。"
      : lang === "zh"
      ? "弱信號驅動的意外變局 — 在傳統預測範圍之外，\n但具有重大潛在影響的情境可能性。"
      : "Weak-signal-driven disruptions beyond conventional forecasts,\nwith significant potential impact on society and industry.",
    C.sC, cData.length
  );
  cData.forEach((d, i) => { cP1(d, i + 1); });

  if (dData.length > 0) {
    sectionDivider(
      lang === "ja" ? "機会シナリオ" : lang === "zh" ? "機會情境" : "Opportunity Scenarios",
      lang === "ja"
        ? "予想（A）と予想外（C）の衝突から生まれる戦略的機会。\n各シナリオはA × Cの交差合成で、衝突スコアとアクションプラン付き。"
        : lang === "zh"
        ? "預期（A）與非預期（C）碰撞所產生的策略機會。\n每個情境由 A × C 交叉合成，附碰撞分數與行動方案。"
        : "Strategic opportunities emerging from A × C collisions.\nEach scenario includes collision scores and action plans.",
      C.sDMain, dData.length
    );
    dData.forEach((d, i) => {
      dP1(d, i + 1);
      dP2(d, i + 1);
      imgSlide(d, C.sDMain, "3", "3", "opportunity_title", i + 1);
    });
  }

  endSlide();

  const suffix = process.env.PPTX_SUFFIX || "";
  const outPath = path.join(BASE, `JRI_Aging_Report_${lang}${suffix}.pptx`);
  await pres.writeFile({ fileName: outPath });
  console.log(`[${lang}] Done! ${pg} slides saved to: ${outPath}`);
  return true;
}

(async () => {
  for (const lang of LANGS) {
    await generateForLang(lang);
  }
})().catch(e => console.error("Error:", e));
