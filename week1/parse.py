"""
Course Prompt Library Parser — v2
Converts tagged .txt source files into Canvas-embeddable HTML.

Tag reference:
  [meta]        Course metadata — renders as header block
  [objectives]  Learning objectives — renders as styled list
  [context]     Instructor-only notes — hidden in student view
  [narration]   Student-facing explanatory text — no copy button
  [discussion]  Verbal discussion prompts — no copy button
  [system]      Session persona prompt — instructor only
  [instructor]  Instructor demonstration prompt — instructor only
  [rubric]      Assessment rubric envelope — never rendered, pipeline use only
  ### S{id}     Standard student prompt — copy button
  ### R{id}     Student contribution prompt — copy button with blank typing line
"""

import re
import sys
from pathlib import Path


def escape_html(text):
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))


def parse_block_tags(source):
    segments = []
    i = 0
    lines = source.split('\n')
    n = len(lines)

    while i < n:
        line = lines[i]

        prompt_match = re.match(r'^###\s+(S|R)([\w.]+)(.*)?$', line.strip())
        if prompt_match:
            ptype = prompt_match.group(1)
            pid = prompt_match.group(2)
            label_extra = prompt_match.group(3).strip()
            full_id = f"{ptype}{pid}"
            content_lines = []
            i += 1
            while i < n and not lines[i].strip() == '###':
                content_lines.append(lines[i])
                i += 1
            i += 1
            raw_content = '\n'.join(content_lines)
            segments.append({
                'tag': 'prompt_s' if ptype == 'S' else 'prompt_r',
                'id': full_id,
                'label': label_extra,
                'content': raw_content
            })
            continue

        tag_match = re.match(r'^\[(\w+)(?:\s+[^\]]+)?\]\s*$', line.strip())
        if tag_match:
            tag = tag_match.group(1).lower()
            opening_line = line.strip()
            content_lines = []
            i += 1
            closing = f'[/{tag}]'
            while i < n and lines[i].strip().lower() != closing:
                content_lines.append(lines[i])
                i += 1
            i += 1
            segments.append({
                'tag': tag,
                'opening': opening_line,
                'content': '\n'.join(content_lines).strip()
            })
            continue

        i += 1

    return segments


def render_meta(content):
    lines = [l.strip() for l in content.strip().split('\n') if l.strip()]
    fields = {}
    for l in lines:
        if ':' in l:
            k, v = l.split(':', 1)
            fields[k.strip()] = v.strip()
    html = '<div class="plib-meta">\n'
    if 'course' in fields:
        html += f'  <div class="plib-meta-course">{escape_html(fields["course"])}</div>\n'
    if 'week' in fields and 'lecture' in fields:
        html += f'  <div class="plib-meta-week">Week {escape_html(fields["week"])} · Lecture {escape_html(fields["lecture"])}</div>\n'
    if 'title' in fields:
        html += f'  <div class="plib-meta-title">{escape_html(fields["title"])}</div>\n'
    meta_items = []
    for k in ['duration', 'platform', 'submission']:
        if k in fields:
            meta_items.append(f'<span><strong>{k.capitalize()}:</strong> {escape_html(fields[k])}</span>')
    if meta_items:
        html += f'  <div class="plib-meta-details">{"&ensp;·&ensp;".join(meta_items)}</div>\n'
    html += '</div>\n'
    return html


def render_objectives(content):
    lines = [l.strip() for l in content.strip().split('\n') if l.strip()]
    html = '<div class="plib-objectives">\n'
    html += '  <div class="plib-objectives-label">Learning Objectives</div>\n'
    html += '  <ol class="plib-objectives-list">\n'
    for line in lines:
        clean = re.sub(r'^\d+\.\s*', '', line)
        html += f'    <li>{escape_html(clean)}</li>\n'
    html += '  </ol>\n'
    html += '</div>\n'
    return html


def render_context(content):
    paras = [p.strip() for p in content.strip().split('\n') if p.strip()]
    html = '<div class="plib-context">\n'
    html += '  <div class="plib-context-label">&#9673; Instructor Note</div>\n'
    html += '  <div class="plib-context-body">\n'
    for p in paras:
        if p.startswith('-'):
            html += f'    <div class="plib-context-bullet">{escape_html(p[1:].strip())}</div>\n'
        else:
            html += f'    <p>{escape_html(p)}</p>\n'
    html += '  </div>\n'
    html += '</div>\n'
    return html


def render_narration(content):
    paras = [p.strip() for p in content.strip().split('\n\n') if p.strip()]
    html = '<div class="plib-narration">\n'
    for para in paras:
        lines = para.split('\n')
        if re.match(r'^\d+\.', lines[0].strip()):
            html += '  <ol class="plib-narration-list">\n'
            for l in lines:
                clean = re.sub(r'^\d+\.\s*', '', l.strip())
                if clean:
                    html += f'    <li>{escape_html(clean)}</li>\n'
            html += '  </ol>\n'
        else:
            joined = ' '.join(l.strip() for l in lines if l.strip())
            html += f'  <p>{escape_html(joined)}</p>\n'
    html += '</div>\n'
    return html


def render_discussion(content):
    lines = [l.strip() for l in content.strip().split('\n') if l.strip()]
    html = '<div class="plib-discussion">\n'
    html += '  <div class="plib-discussion-label">&#128172; Discussion</div>\n'
    html += '  <ul class="plib-discussion-list">\n'
    for line in lines:
        if line.startswith('-'):
            line = line[1:].strip()
        html += f'    <li>{escape_html(line)}</li>\n'
    html += '</ul>\n'
    html += '</div>\n'
    return html


def render_system(content, block_index):
    bid = f"system_{block_index}"
    escaped = escape_html(content.strip())
    return f'''<div class="plib-system">
  <div class="plib-system-label">&#9881; Session System Prompt <span class="plib-system-note">(Instructor: paste this into Hokie AI before class begins)</span></div>
  <div class="plib-prompt-text" id="text_{bid}">{escaped}</div>
  <button class="plib-copy-btn" onclick="copyPrompt('text_{bid}', this)">&#128203; Copy system prompt</button>
</div>
'''


def render_instructor(content, block_index):
    bid = f"instructor_{block_index}"
    escaped = escape_html(content.strip())
    return f'''<div class="plib-instructor">
  <div class="plib-instructor-label">&#128065; Instructor Demonstration <span class="plib-instructor-note">(Students observe — do not copy)</span></div>
  <div class="plib-prompt-text" id="text_{bid}">{escaped}</div>
  <button class="plib-copy-btn" onclick="copyPrompt('text_{bid}', this)">&#128203; Copy for demonstration</button>
</div>
'''


def extract_dashed_content(raw):
    lines = raw.split('\n')
    inside = False
    collected = []
    for line in lines:
        if line.strip() == '----------':
            if not inside:
                inside = True
            else:
                break
        elif inside:
            collected.append(line)
    return '\n'.join(collected).strip()


def is_identity_block(full_id):
    """R2.0, R3.0, R4.0 etc. — any R block ending in .0 is a session opener."""
    return re.match(r'^R\d+\.0$', full_id) is not None


def build_student_copy_text(full_id, raw_content, label=''):
    inner = extract_dashed_content(raw_content)
    if full_id.startswith('R'):
        if is_identity_block(full_id):
            # Identity block: preserve the full raw content as-is between the ### markers
            # This includes the student typing zone AND the session instruction zone
            return f"### {full_id}{' ' + label if label else ''}\n{raw_content.strip()}\n###"
        else:
            # Contribution block: blank line between dashes, no inner content
            return f"### {full_id}{' ' + label if label else ''}\n----------\n\n----------\n###"
    else:
        return f"### {full_id}\n----------\n{inner}\n----------\n###"


def render_prompt_s(seg, block_index):
    pid = seg['id']
    raw = seg['content']
    inner = extract_dashed_content(raw)
    copy_text = build_student_copy_text(pid, raw)
    bid = f"prompt_{block_index}"
    return f'''<div class="plib-prompt-s">
  <div class="plib-prompt-header">
    <span class="plib-prompt-id">{escape_html(pid)}</span>
    <span class="plib-prompt-type-label">Student Prompt</span>
  </div>
  <div class="plib-prompt-text" id="text_{bid}">{escape_html(copy_text)}</div>
  <div class="plib-prompt-display">{escape_html(inner)}</div>
  <button class="plib-copy-btn" onclick="copyPrompt('text_{bid}', this)">&#128203; Copy prompt</button>
</div>
'''


def render_prompt_r(seg, block_index):
    pid = seg['id']
    label = seg.get('label', '')
    raw = seg['content']
    copy_text = build_student_copy_text(pid, raw, label)
    bid = f"prompt_{block_index}"

    if is_identity_block(pid):
        return f'''<div class="plib-prompt-identity">
  <div class="plib-prompt-header">
    <span class="plib-prompt-id plib-identity-id">{escape_html(pid)}</span>
    <span class="plib-prompt-type-label plib-identity-label">Session Opener</span>
  </div>
  <div class="plib-prompt-text" id="text_{bid}">{escape_html(copy_text)}</div>
  <div class="plib-identity-instruction">Copy this block into Hokie AI. Type your VT PID between the dashed lines, then copy and paste the closing marker to start your session.</div>
  <button class="plib-copy-btn plib-copy-btn-identity" onclick="copyPrompt('text_{bid}', this)">&#128203; Copy session opener</button>
</div>
'''
    else:
        return f'''<div class="plib-prompt-r">
  <div class="plib-prompt-header">
    <span class="plib-prompt-id">{escape_html(pid)}</span>
    <span class="plib-prompt-type-label plib-reflect-label">Your Contribution</span>
  </div>
  <div class="plib-prompt-text" id="text_{bid}">{escape_html(copy_text)}</div>
  <div class="plib-reflect-instruction">Copy the block below into Hokie AI. Type your response between the dashed lines, then copy and paste the closing marker.</div>
  <button class="plib-copy-btn plib-copy-btn-reflect" onclick="copyPrompt('text_{bid}', this)">&#128203; Copy contribution block</button>
</div>
'''


CSS = """
<style>
:root {
  --c-bg: #ffffff; --c-border: rgba(0,0,0,0.10); --c-text: #1a1a1a; --c-muted: #555;
  --c-meta-bg: #f4f6f9; --c-meta-border: #d0d7e2;
  --c-obj-bg: #eef4fb; --c-obj-border: #b8d0ed; --c-obj-accent: #2a6db5;
  --c-ctx-bg: #fffbf0; --c-ctx-border: #e8d8a0; --c-ctx-label: #7a5c00;
  --c-nar-bg: #f9f9f9; --c-nar-border: #ddd;
  --c-dis-bg: #f0f4ff; --c-dis-border: #b0bfee; --c-dis-label: #2a3fa0;
  --c-sys-bg: #f3f0ff; --c-sys-border: #c4b8f0; --c-sys-label: #4a30a0;
  --c-ins-bg: #fff0f4; --c-ins-border: #f0b8c8; --c-ins-label: #a03050;
  --c-s-bg: #f0faf4; --c-s-border: #a0d8b8; --c-s-id: #1a6b40;
  --c-r-bg: #fff8f0; --c-r-border: #f0c890; --c-r-id: #8a4a00;
  --c-i-bg: #f0f0ff; --c-i-border: #b0b0e8; --c-i-id: #3a3a9a;
  --c-btn: #1a6b40; --c-btn-r: #8a4a00; --c-btn-i: #3a3a9a; --radius: 8px;
  --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}
.plib-wrap { font-family: var(--font); color: var(--c-text); max-width: 800px; margin: 0 auto; padding: 1rem 0; }
.plib-meta { background: var(--c-meta-bg); border: 1px solid var(--c-meta-border); border-radius: var(--radius); padding: 1.25rem 1.5rem; margin-bottom: 1.5rem; }
.plib-meta-course { font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--c-muted); margin-bottom: 4px; }
.plib-meta-title { font-size: 20px; font-weight: 600; margin: 4px 0 8px; }
.plib-meta-week { font-size: 13px; color: var(--c-muted); margin-bottom: 2px; }
.plib-meta-details { font-size: 12px; color: var(--c-muted); margin-top: 8px; }
.plib-objectives { background: var(--c-obj-bg); border-left: 4px solid var(--c-obj-accent); border-radius: var(--radius); padding: 1rem 1.25rem; margin-bottom: 1.5rem; }
.plib-objectives-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--c-obj-accent); font-weight: 600; margin-bottom: 8px; }
.plib-objectives-list { margin: 0; padding-left: 1.25rem; }
.plib-objectives-list li { margin-bottom: 6px; font-size: 14px; line-height: 1.6; }
.plib-context { background: var(--c-ctx-bg); border: 1px solid var(--c-ctx-border); border-radius: var(--radius); padding: 1rem 1.25rem; margin-bottom: 1rem; }
.plib-context-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--c-ctx-label); font-weight: 600; margin-bottom: 8px; }
.plib-context-body p { margin: 4px 0; font-size: 13px; line-height: 1.6; color: var(--c-muted); }
.plib-context-bullet { font-size: 13px; color: var(--c-muted); padding-left: 1rem; position: relative; margin-bottom: 3px; }
.plib-context-bullet::before { content: "–"; position: absolute; left: 0; }
.plib-narration { background: var(--c-nar-bg); border-left: 3px solid var(--c-nar-border); padding: 0.9rem 1.25rem; margin-bottom: 1rem; border-radius: 0 var(--radius) var(--radius) 0; }
.plib-narration p { margin: 0 0 8px; font-size: 14px; line-height: 1.7; }
.plib-narration p:last-child { margin-bottom: 0; }
.plib-narration-list { margin: 4px 0; padding-left: 1.25rem; }
.plib-narration-list li { font-size: 14px; line-height: 1.6; margin-bottom: 4px; }
.plib-discussion { background: var(--c-dis-bg); border: 1px solid var(--c-dis-border); border-radius: var(--radius); padding: 1rem 1.25rem; margin-bottom: 1rem; }
.plib-discussion-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--c-dis-label); font-weight: 600; margin-bottom: 8px; }
.plib-discussion-list { margin: 0; padding-left: 1.25rem; }
.plib-discussion-list li { font-size: 14px; line-height: 1.6; margin-bottom: 6px; color: var(--c-dis-label); }
.plib-system { background: var(--c-sys-bg); border: 1px solid var(--c-sys-border); border-radius: var(--radius); padding: 1rem 1.25rem; margin-bottom: 1rem; }
.plib-system-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--c-sys-label); font-weight: 600; margin-bottom: 8px; }
.plib-system-note { font-weight: 400; text-transform: none; letter-spacing: 0; font-style: italic; }
.plib-instructor { background: var(--c-ins-bg); border: 1px solid var(--c-ins-border); border-radius: var(--radius); padding: 1rem 1.25rem; margin-bottom: 1rem; }
.plib-instructor-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--c-ins-label); font-weight: 600; margin-bottom: 8px; }
.plib-instructor-note { font-weight: 400; text-transform: none; letter-spacing: 0; font-style: italic; }
.plib-prompt-text { display: none; }
.plib-prompt-display { font-size: 14px; line-height: 1.7; white-space: pre-wrap; background: rgba(255,255,255,0.6); border-radius: 4px; padding: 0.6rem 0.8rem; margin-bottom: 10px; }
.plib-prompt-s { background: var(--c-s-bg); border: 1px solid var(--c-s-border); border-radius: var(--radius); padding: 1rem 1.25rem; margin-bottom: 1.25rem; }
.plib-prompt-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.plib-prompt-id { font-size: 12px; font-weight: 700; color: var(--c-s-id); font-family: monospace; background: rgba(26,107,64,0.1); padding: 2px 7px; border-radius: 4px; }
.plib-prompt-type-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.07em; color: var(--c-muted); }
.plib-prompt-r { background: var(--c-r-bg); border: 1px solid var(--c-r-border); border-radius: var(--radius); padding: 1rem 1.25rem; margin-bottom: 1.25rem; }
.plib-reflect-label { color: var(--c-r-id) !important; }
.plib-prompt-r .plib-prompt-id { color: var(--c-r-id); background: rgba(138,74,0,0.1); }
.plib-reflect-instruction { font-size: 13px; color: var(--c-muted); font-style: italic; margin-bottom: 10px; }
.plib-prompt-identity { background: var(--c-i-bg); border: 2px solid var(--c-i-border); border-radius: var(--radius); padding: 1rem 1.25rem; margin-bottom: 1.25rem; }
.plib-identity-id { color: var(--c-i-id) !important; background: rgba(58,58,154,0.1) !important; }
.plib-identity-label { color: var(--c-i-id) !important; }
.plib-identity-instruction { font-size: 13px; color: var(--c-muted); font-style: italic; margin-bottom: 10px; }
.plib-copy-btn { display: inline-block; padding: 7px 14px; font-size: 13px; font-weight: 500; border: 1.5px solid var(--c-btn); background: transparent; color: var(--c-btn); border-radius: 6px; cursor: pointer; transition: background 0.15s, color 0.15s; }
.plib-copy-btn:hover { background: var(--c-btn); color: #fff; }
.plib-copy-btn-reflect { border-color: var(--c-btn-r); color: var(--c-btn-r); }
.plib-copy-btn-reflect:hover { background: var(--c-btn-r); color: #fff; }
.plib-copy-btn-identity { border-color: var(--c-btn-i); color: var(--c-btn-i); }
.plib-copy-btn-identity:hover { background: var(--c-btn-i); color: #fff; }
.plib-copy-btn.copied { background: #333; color: #fff; border-color: #333; }
</style>
"""

JS = """
<script>
function copyPrompt(id, btn) {
  var el = document.getElementById(id);
  if (!el) return;
  var text = el.innerText || el.textContent;
  navigator.clipboard.writeText(text).then(function() {
    var orig = btn.innerHTML;
    btn.innerHTML = '&#10003; Copied';
    btn.classList.add('copied');
    setTimeout(function() { btn.innerHTML = orig; btn.classList.remove('copied'); }, 2000);
  }).catch(function() {
    var ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    var orig = btn.innerHTML;
    btn.innerHTML = '&#10003; Copied';
    btn.classList.add('copied');
    setTimeout(function() { btn.innerHTML = orig; btn.classList.remove('copied'); }, 2000);
  });
}
</script>
"""


def parse_and_render(source, mode='student'):
    segments = parse_block_tags(source)
    html_parts = []
    block_index = 0

    for seg in segments:
        tag = seg['tag']
        block_index += 1

        if tag == 'meta':
            html_parts.append(render_meta(seg['content']))
        elif tag == 'objectives':
            html_parts.append(render_objectives(seg['content']))
        elif tag == 'context':
            if mode == 'instructor':
                html_parts.append(render_context(seg['content']))
        elif tag == 'narration':
            html_parts.append(render_narration(seg['content']))
        elif tag == 'discussion':
            html_parts.append(render_discussion(seg['content']))
        elif tag == 'system':
            if mode == 'instructor':
                html_parts.append(render_system(seg['content'], block_index))
        elif tag == 'instructor':
            if mode == 'instructor':
                html_parts.append(render_instructor(seg['content'], block_index))
        elif tag == 'rubric':
            pass  # pipeline only — never rendered
        elif tag == 'prompt_s':
            html_parts.append(render_prompt_s(seg, block_index))
        elif tag == 'prompt_r':
            html_parts.append(render_prompt_r(seg, block_index))

    body = '\n'.join(html_parts)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Prompt Library</title>
{CSS}
</head>
<body>
<div class="plib-wrap">
{body}
</div>
{JS}
</body>
</html>"""


def main():
    if len(sys.argv) < 2:
        print("Usage: python parse.py <source.txt> [student|instructor]")
        sys.exit(1)
    source_path = Path(sys.argv[1])
    mode = sys.argv[2] if len(sys.argv) > 2 else 'student'
    if not source_path.exists():
        print(f"File not found: {source_path}")
        sys.exit(1)
    source = source_path.read_text(encoding='utf-8')
    output_dir = Path(__file__).parent.parent / 'output'
    output_dir.mkdir(exist_ok=True)
    stem = source_path.stem
    out_path = output_dir / f"{stem}_{mode}.html"
    html = parse_and_render(source, mode=mode)
    out_path.write_text(html, encoding='utf-8')
    print(f"Written: {out_path}")


if __name__ == '__main__':
    main()
