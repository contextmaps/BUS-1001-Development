"""
Rubric Envelope Extractor
Reads a lecture source .txt file and extracts all [rubric] blocks,
pairing each with its referenced standard prompt text from the same file.

Output: <stem>_rubric_envelope.txt

Usage:
    python extract_rubric.py <source.txt> [output_dir]

Rubric envelope format in source file:
    [rubric id: R2.1]
    type: reflection
    context_prompt: S2.1
    directive: ...
    narration: ...
    dimensions: dim1, dim2, dim3
    [/rubric]
"""

import re
import sys
from pathlib import Path


def parse_rubric_blocks(source):
    """Extract all [rubric id: ...] blocks with their attributes."""
    rubrics = []
    lines = source.split('\n')
    n = len(lines)
    i = 0

    while i < n:
        line = lines[i].strip()

        # Match [rubric id: X] opening
        rubric_match = re.match(r'^\[rubric\s+id:\s*([\w.]+)\]', line, re.IGNORECASE)
        if rubric_match:
            rubric_id = rubric_match.group(1)
            content_lines = []
            i += 1
            while i < n and lines[i].strip().lower() != '[/rubric]':
                content_lines.append(lines[i])
                i += 1
            i += 1  # skip [/rubric]

            # Parse key: value fields from content
            fields = {}
            for cl in content_lines:
                cl = cl.strip()
                if ':' in cl:
                    k, v = cl.split(':', 1)
                    fields[k.strip().lower()] = v.strip()

            rubrics.append({
                'id': rubric_id,
                'type': fields.get('type', 'contribution'),
                'context_prompt': fields.get('context_prompt', ''),
                'directive': fields.get('directive', ''),
                'narration': fields.get('narration', ''),
                'dimensions': [d.strip() for d in fields.get('dimensions', '').split(',') if d.strip()]
            })
            continue

        i += 1

    return rubrics


def extract_standard_prompts(source):
    """
    Extract all ### S{id} blocks from the source file.
    Returns dict: { 'S2.1': 'prompt text here', ... }
    """
    prompts = {}
    lines = source.split('\n')
    n = len(lines)
    i = 0

    while i < n:
        line = lines[i].strip()
        s_match = re.match(r'^###\s+(S[\w.]+)', line)
        if s_match:
            pid = s_match.group(1)
            content_lines = []
            i += 1
            while i < n and lines[i].strip() != '###':
                content_lines.append(lines[i])
                i += 1
            i += 1

            # Extract content between dashes
            raw = '\n'.join(content_lines)
            dash_lines = raw.split('\n')
            inside = False
            collected = []
            for dl in dash_lines:
                if dl.strip() == '----------':
                    if not inside:
                        inside = True
                    else:
                        break
                elif inside:
                    collected.append(dl)
            prompts[pid] = '\n'.join(collected).strip()
            continue
        i += 1

    return prompts


def extract_narration_before_contribution(source, contribution_id):
    """
    Find the narration block immediately preceding an R{id} block.
    Returns narration text or empty string.
    """
    lines = source.split('\n')
    n = len(lines)
    last_narration = ''
    i = 0

    while i < n:
        line = lines[i].strip()

        # Capture narration blocks as we pass them
        if line.lower() == '[narration]':
            content_lines = []
            i += 1
            while i < n and lines[i].strip().lower() != '[/narration]':
                content_lines.append(lines[i])
                i += 1
            last_narration = '\n'.join(content_lines).strip()
            i += 1
            continue

        # When we hit the target R block, return the last narration seen
        r_match = re.match(r'^###\s+' + re.escape(contribution_id) + r'\b', line)
        if r_match:
            return last_narration

        i += 1

    return ''


def build_rubric_envelope(source):
    """
    Build the complete rubric envelope document from a source file.
    """
    rubrics = parse_rubric_blocks(source)
    standard_prompts = extract_standard_prompts(source)

    if not rubrics:
        return None

    lines = []
    lines.append('[rubric_envelope]')

    # Extract meta info
    meta_match = re.search(r'\[meta\](.*?)\[/meta\]', source, re.DOTALL | re.IGNORECASE)
    if meta_match:
        meta_lines = [l.strip() for l in meta_match.group(1).strip().split('\n') if ':' in l]
        for ml in meta_lines:
            lines.append(ml)
    lines.append('')

    for rubric in rubrics:
        rid = rubric['id']
        context_pid = rubric['context_prompt']

        lines.append(f'[rubric id: {rid}]')
        lines.append(f'type: {rubric["type"]}')
        lines.append(f'context_prompt_id: {context_pid}')
        lines.append('')

        # Include directive
        lines.append('[directive]')
        lines.append(rubric['directive'])
        lines.append('[/directive]')
        lines.append('')

        # Include narration context from source
        narration = extract_narration_before_contribution(source, rid)
        if not narration and rubric['narration']:
            narration = rubric['narration']
        if narration:
            lines.append('[narration_context]')
            lines.append(narration)
            lines.append('[/narration_context]')
            lines.append('')

        # Include the referenced standard prompt text
        if context_pid and context_pid in standard_prompts:
            lines.append(f'[context_prompt id: {context_pid}]')
            lines.append(standard_prompts[context_pid])
            lines.append(f'[/context_prompt]')
            lines.append('')

        # Assessment dimensions
        if rubric['dimensions']:
            lines.append('[dimensions]')
            for dim in rubric['dimensions']:
                lines.append(f'- {dim}')
            lines.append('[/dimensions]')

        lines.append(f'[/rubric]')
        lines.append('')

    lines.append('[/rubric_envelope]')
    return '\n'.join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python extract_rubric.py <source.txt> [output_dir]")
        sys.exit(1)

    source_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else source_path.parent

    if not source_path.exists():
        print(f"File not found: {source_path}")
        sys.exit(1)

    output_dir.mkdir(exist_ok=True)
    source = source_path.read_text(encoding='utf-8')

    envelope = build_rubric_envelope(source)
    if not envelope:
        print("No [rubric] blocks found in source file.")
        sys.exit(1)

    stem = source_path.stem
    out_path = output_dir / f"{stem}_rubric_envelope.txt"
    out_path.write_text(envelope, encoding='utf-8')
    print(f"Written: {out_path}")

    # Summary
    rubrics = parse_rubric_blocks(source)
    standard_prompts = extract_standard_prompts(source)
    print(f"\nFound {len(rubrics)} rubric block(s):")
    for r in rubrics:
        cp = r['context_prompt']
        found = "✓" if cp in standard_prompts else "✗ NOT FOUND"
        print(f"  {r['id']} | type: {r['type']} | context_prompt: {cp} {found} | dimensions: {len(r['dimensions'])}")


if __name__ == '__main__':
    main()
