import zipfile
import xml.etree.ElementTree as ET
import os
import re
from collections import Counter

def get_slides_text_runs(pptx_path):
    slides_data = []
    try:
        with zipfile.ZipFile(pptx_path, 'r') as z:
            slide_files = sorted([f for f in z.namelist() if f.startswith('ppt/slides/slide') and f.endswith('.xml')], 
                                 key=lambda x: int(re.search(r'slide(\d+)', x).group(1)))
            for slide_file in slide_files:
                with z.open(slide_file) as f:
                    tree = ET.parse(f)
                    root = tree.getroot()
                    text_runs = []
                    # DrawingML namespace
                    for t in root.iter('{http://schemas.openxmlformats.org/drawingml/2006/main}t'):
                        if t.text:
                            text_runs.append(t.text.strip())
                    slides_data.append(text_runs)
    except Exception as e:
        print(f"Error processing {pptx_path}: {e}")
    return slides_data

def audit_pptx(path, lang='ja'):
    print(f"\nAudit Report for: {os.path.basename(path)}")
    slides = get_slides_text_runs(path)
    
    # 1. Section Detection
    keywords = {
        'A': '予想シナリオ' if lang == 'ja' else '預期情境',
        'C': '予想外シナリオ' if lang == 'ja' else '非預期情境',
        'D': '機会シナリオ' if lang == 'ja' else '機會情境'
    }
    section_counts = Counter()
    section_map = {} # slide_idx -> section
    
    for i, slide_runs in enumerate(slides):
        full_text = " ".join(slide_runs)
        for sec, kw in keywords.items():
            if kw in full_text:
                section_counts[sec] += 1
                section_map[i] = sec
    
    print(f"Section Counts: {dict(section_counts)}")

    # 2. Duplicate Titles (likely scenario titles)
    # Filter: 6-40 chars, appears >= 2 times
    # Exclude common labels
    exclude = {"成果概要", "成果總覽", "Expected", "Unexpected", "Opportunity", "Next Steps", "Table of Contents"}
    all_runs = []
    for slide_runs in slides:
        for run in slide_runs:
            if 6 <= len(run) <= 60:
                all_runs.append(run)
    
    run_counts = Counter(all_runs)
    dupes = {k: v for k, v in run_counts.items() if v >= 2 and k not in exclude}
    print(f"Duplicate title candidates (potential scenario labels): {len(dupes)}")

    # 3. Scenario Samples (First 5 from each section)
    for sec in ['A', 'C', 'D']:
        samples = []
        for idx, s_type in section_map.items():
            if s_type == sec:
                # Attempt to find the "Title" of the scenario - usually one of the first few runs
                # that isn't the section keyword itself
                for run in slides[idx]:
                    if 5 < len(run) < 60 and keywords[sec] not in run and run not in exclude:
                        samples.append(run)
                        break
        print(f"Sample {sec} scenarios: {samples[:5]}")

    # 4. Suspicious Strings
    suspicious = ["nan", "None", "undefined", "null", "[]", "{}", "---", "TODO"]
    issues = Counter()
    for i, slide_runs in enumerate(slides):
        full_text = " ".join(slide_runs).lower()
        for s in suspicious:
            if s.lower() in full_text:
                issues[s] += 1
    
    if issues:
        print(f"Suspicious strings found: {dict(issues)}")
    else:
        print("Suspicious strings: None")

print("--- ANALYZING JA ---")
audit_pptx("data/output/jri_aging/JRI_Aging_Report_ja.pptx", 'ja')
print("\n--- ANALYZING ZH ---")
audit_pptx("data/output/jri_aging/JRI_Aging_Report_zh.pptx", 'zh')
