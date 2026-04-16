"""
Thread Parser — v2
Converts a saved ChatGPT / HokieAI thread HTML into two structured files:

  <stem>_parsed.txt       Full archival record of all turns
  <stem>_contributions.txt  Student contribution blocks only (assessment payload)

Usage:
    python thread_parser.py <thread.html> [output_dir]

Turn types detected:
    standard     — contains ### S{id} marker (scaffolded student prompt)
    contribution — contains ### R{id} marker (student's own thinking)
    context      — conversational turn without a marker
    assistant    — AI response turn
"""

import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup


def extract_turns(html_path):
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()

    soup = BeautifulSoup(html, 'html.parser')
    sections = soup.find_all('section', attrs={'data-turn': True})

    turns = []
    for section in sections:
        role = section.get('data-turn', 'unknown')

        if role == 'user':
            msg_div = section.find('div', class_=lambda c: c and 'whitespace-pre-wrap' in c)
            text = msg_div.get_text(strip=True) if msg_div else section.get_text(strip=True)
        else:
            md_div = section.find('div', class_=lambda c: c and 'markdown' in str(c))
            text = md_div.get_text(separator='\n', strip=True) if md_div else section.get_text(strip=True)

        text = re.sub(r'\n{3,}', '\n\n', text).strip()
        turns.append((role, text))

    return turns


def classify_turn(role, text):
    if role == 'assistant':
        return 'assistant', None
    s_match = re.search(r'###\s+S([\w.]+)', text)
    r_match = re.search(r'###\s+R([\w.]+)', text)
    if s_match:
        return 'standard', f"S{s_match.group(1)}"
    elif r_match:
        return 'contribution', f"R{r_match.group(1)}"
    else:
        return 'context', None


def extract_contribution_content(text, prompt_id):
    """Extract student-written content between dashed lines in a contribution block."""
    pattern = r'###\s+' + re.escape(prompt_id) + r'[^\n]*\n-{5,}\n(.*?)\n-{5,}\n###'
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: return everything after the opening marker
    fallback = re.search(r'###\s+' + re.escape(prompt_id) + r'[^\n]*\n(.*)', text, re.DOTALL)
    return fallback.group(1).strip() if fallback else text


def build_parsed_output(turns, source='chatgpt'):
    """Full archival record of all turns."""
    lines = []
    lines.append('[meta]')
    lines.append(f'source: {source}')
    lines.append(f'turns: {len(turns)}')
    lines.append('[/meta]')
    lines.append('')

    for i, (role, text) in enumerate(turns):
        turn_num = i + 1
        turn_type, prompt_id = classify_turn(role, text)

        if turn_type == 'assistant':
            header = f'[turn {turn_num} | role: assistant]'
        elif turn_type == 'standard':
            header = f'[turn {turn_num} | role: user | type: standard | id: {prompt_id}]'
        elif turn_type == 'contribution':
            header = f'[turn {turn_num} | role: user | type: contribution | id: {prompt_id}]'
        else:
            header = f'[turn {turn_num} | role: user | type: context]'

        lines.append(header)
        lines.append(text)

        if turn_type == 'contribution' and prompt_id:
            inner = extract_contribution_content(text, prompt_id)
            if inner:
                lines.append('')
                lines.append(f'[contribution_content id: {prompt_id}]')
                lines.append(inner)
                lines.append(f'[/contribution_content]')

        lines.append(f'[/turn]')
        lines.append('')

    return '\n'.join(lines)


def build_contributions_output(turns, source='chatgpt'):
    """
    Contributions-only file — assessment payload.
    Contains only the student's own thinking, keyed by ID,
    with the immediately preceding AI response included for context.
    """
    lines = []
    lines.append('[meta]')
    lines.append(f'source: {source}')
    contribution_count = sum(
        1 for role, text in turns
        if classify_turn(role, text)[0] == 'contribution'
    )
    lines.append(f'contributions: {contribution_count}')
    lines.append('[/meta]')
    lines.append('')

    # Build a lookup of what preceded each contribution
    for i, (role, text) in enumerate(turns):
        turn_type, prompt_id = classify_turn(role, text)

        if turn_type != 'contribution':
            continue

        # Find the immediately preceding AI response
        preceding_ai = None
        for j in range(i - 1, -1, -1):
            prev_role, prev_text = turns[j]
            if prev_role == 'assistant':
                preceding_ai = prev_text
                break

        # Find the standard prompt this contribution responds to
        preceding_standard_id = None
        preceding_standard_text = None
        for j in range(i - 1, -1, -1):
            prev_role, prev_text = turns[j]
            prev_type, prev_id = classify_turn(prev_role, prev_text)
            if prev_type == 'standard':
                preceding_standard_id = prev_id
                preceding_standard_text = prev_text
                break

        inner = extract_contribution_content(text, prompt_id)

        lines.append(f'[contribution id: {prompt_id}]')

        if preceding_standard_id:
            lines.append(f'[context_prompt id: {preceding_standard_id}]')
            if preceding_standard_text:
                from_standard = extract_dashed_content_from_standard(preceding_standard_text)
                lines.append(from_standard or preceding_standard_text[:500])
            lines.append(f'[/context_prompt]')
            lines.append('')

        if preceding_ai:
            lines.append(f'[ai_response]')
            lines.append(preceding_ai[:1000])  # cap at 1000 chars for token efficiency
            lines.append(f'[/ai_response]')
            lines.append('')

        lines.append(f'[student_text]')
        lines.append(inner)
        lines.append(f'[/student_text]')
        lines.append(f'[/contribution]')
        lines.append('')

    return '\n'.join(lines)


def extract_dashed_content_from_standard(text):
    """Extract the prompt text from inside a standard block's dashes."""
    lines = text.split('\n')
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


def build_api_messages(turns, system_prompt=None, rubric_envelope=None):
    """
    Build API-ready message list from parsed turns.
    Optionally include system prompt and rubric envelope context.
    """
    messages = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    if rubric_envelope:
        messages.append({
            "role": "user",
            "content": f"[RUBRIC ENVELOPE]\n\n{rubric_envelope}"
        })
        messages.append({
            "role": "assistant",
            "content": "Rubric envelope received. Ready to assess student contribution."
        })

    student_parts = []
    for i, (role, text) in enumerate(turns):
        turn_type, prompt_id = classify_turn(role, text)
        turn_num = i + 1

        if turn_type == 'standard':
            student_parts.append(f"[TURN {turn_num} — STUDENT STANDARD PROMPT {prompt_id}]\n{text}")
        elif turn_type == 'contribution':
            inner = extract_contribution_content(text, prompt_id) or text
            student_parts.append(f"[TURN {turn_num} — STUDENT CONTRIBUTION {prompt_id}]\n{inner}")
        elif turn_type == 'assistant':
            student_parts.append(f"[TURN {turn_num} — AI RESPONSE]\n{text}")
        else:
            student_parts.append(f"[TURN {turn_num} — CONTEXT]\n{text}")

    messages.append({
        "role": "user",
        "content": "[STUDENT SUBMISSION THREAD]\n\n" + '\n\n'.join(student_parts) + "\n\nPlease assess this submission."
    })

    return messages


def main():
    if len(sys.argv) < 2:
        print("Usage: python thread_parser.py <thread.html> [output_dir]")
        sys.exit(1)

    html_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else html_path.parent

    if not html_path.exists():
        print(f"File not found: {html_path}")
        sys.exit(1)

    output_dir.mkdir(exist_ok=True)
    stem = html_path.stem

    print(f"Parsing: {html_path}")
    turns = extract_turns(html_path)
    print(f"Found {len(turns)} turns")

    # Output 1 — full archival record
    parsed = build_parsed_output(turns, source='chatgpt')
    parsed_path = output_dir / f"{stem}_parsed.txt"
    parsed_path.write_text(parsed, encoding='utf-8')
    print(f"Written: {parsed_path}")

    # Output 2 — contributions only
    contributions = build_contributions_output(turns, source='chatgpt')
    contrib_path = output_dir / f"{stem}_contributions.txt"
    contrib_path.write_text(contributions, encoding='utf-8')
    print(f"Written: {contrib_path}")

    # Summary
    print('\n--- TURN SUMMARY ---')
    for i, (role, text) in enumerate(turns):
        turn_type, prompt_id = classify_turn(role, text)
        pid_str = f" [{prompt_id}]" if prompt_id else ""
        preview = text[:80].replace('\n', ' ')
        print(f"Turn {i+1:2d} | {role:9s} | {turn_type:12s}{pid_str:8s} | {preview}...")


if __name__ == '__main__':
    main()
