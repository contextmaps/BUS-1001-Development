"""
API Builder — Assessment Pipeline
Combines rubric envelope + student contributions into Azure OpenAI API calls.
Parses responses into tagged assessment files.

Usage:
    python api_builder.py <rubric_envelope.txt> <contributions.txt> [output_dir]

    Or for batch processing across multiple contribution files:
    python api_builder.py <rubric_envelope.txt> --batch <dir_of_contribution_files> [output_dir]

Output per student per contribution:
    <student_id>_<contribution_id>_assessment.txt

Requires environment variable or config:
    AZURE_OPENAI_ENDPOINT   e.g. https://bus-1001-development.openai.azure.com/
    AZURE_OPENAI_KEY        your API key
    AZURE_DEPLOYMENT_NAME   your deployment name (e.g. gpt-4o)

Or set them directly in the CONFIG block below for local testing.
"""

import re
import sys
import os
import json
import requests
from pathlib import Path
from datetime import datetime


# ── Configuration ──────────────────────────────────────────────────────────────
# Set these via environment variables or directly here for testing
AZURE_ENDPOINT = os.environ.get('AZURE_OPENAI_ENDPOINT', '')
AZURE_KEY = os.environ.get('AZURE_OPENAI_KEY', '')
AZURE_DEPLOYMENT = os.environ.get('AZURE_DEPLOYMENT_NAME', 'gpt-4o')
API_VERSION = '2024-02-01'

# Assessment system prompt — instructor can revise this per course
ASSESSMENT_SYSTEM_PROMPT = """You are an expert educational assessor evaluating student contributions from an AI literacy course.

Your role is to evaluate the quality of a student's thinking and engagement — not the polish of their writing.

You receive:
1. A rubric envelope describing the contribution type, directive, context, and assessment dimensions
2. The student's contribution text

You produce a structured assessment with:
- A band score: Developing / Satisfactory / Strong
- Dimension-by-dimension feedback (2-3 sentences each), grounded in specific evidence from the student's own words
- A brief summary (2-3 sentences) with one concrete suggestion for improvement

Be direct, specific, and constructive. Never evaluate what the student did not write — only what they did.
If the contribution appears to be a placeholder or contains no substantive content, flag it clearly.

Always respond using the exact tagged format specified in the user message."""


# ── Rubric envelope parser ──────────────────────────────────────────────────────
def parse_rubric_envelope(envelope_text):
    """
    Parse rubric envelope file into a dict keyed by contribution ID.
    Returns { 'R2.1': { type, directive, narration, context_prompt_id,
                         context_prompt_text, dimensions } }
    """
    rubrics = {}
    blocks = re.findall(
        r'\[rubric id:\s*([\w.]+)\](.*?)\[/rubric\]',
        envelope_text, re.DOTALL | re.IGNORECASE
    )

    for rid, block in blocks:
        rid = rid.strip()
        r = {'id': rid}

        # type
        t = re.search(r'^type:\s*(.+)$', block, re.MULTILINE)
        r['type'] = t.group(1).strip() if t else 'contribution'

        # context_prompt_id
        cp = re.search(r'^context_prompt_id:\s*(.+)$', block, re.MULTILINE)
        r['context_prompt_id'] = cp.group(1).strip() if cp else ''

        # directive
        d = re.search(r'\[directive\](.*?)\[/directive\]', block, re.DOTALL)
        r['directive'] = d.group(1).strip() if d else ''

        # narration context
        nc = re.search(r'\[narration_context\](.*?)\[/narration_context\]', block, re.DOTALL)
        r['narration'] = nc.group(1).strip() if nc else ''

        # context prompt text
        cpt = re.search(r'\[context_prompt[^\]]*\](.*?)\[/context_prompt\]', block, re.DOTALL)
        r['context_prompt_text'] = cpt.group(1).strip() if cpt else ''

        # dimensions
        dims_block = re.search(r'\[dimensions\](.*?)\[/dimensions\]', block, re.DOTALL)
        if dims_block:
            r['dimensions'] = [
                l.strip().lstrip('- ') for l in dims_block.group(1).strip().split('\n')
                if l.strip().lstrip('- ')
            ]
        else:
            r['dimensions'] = []

        rubrics[rid] = r

    return rubrics


# ── Contributions file parser ───────────────────────────────────────────────────
def parse_contributions(contributions_text):
    """
    Parse contributions file into a list of contribution dicts.
    Returns [ { id, context_prompt_id, context_prompt_text,
                ai_response, student_text } ]
    """
    contributions = []
    blocks = re.findall(
        r'\[contribution id:\s*([\w.]+)\](.*?)\[/contribution\]',
        contributions_text, re.DOTALL | re.IGNORECASE
    )

    for cid, block in blocks:
        cid = cid.strip()
        c = {'id': cid}

        cp = re.search(r'\[context_prompt[^\]]*\](.*?)\[/context_prompt\]', block, re.DOTALL)
        c['context_prompt_text'] = cp.group(1).strip() if cp else ''

        ai = re.search(r'\[ai_response\](.*?)\[/ai_response\]', block, re.DOTALL)
        c['ai_response'] = ai.group(1).strip() if ai else ''

        st = re.search(r'\[student_text\](.*?)\[/student_text\]', block, re.DOTALL)
        c['student_text'] = st.group(1).strip() if st else ''

        contributions.append(c)

    return contributions


# ── API call builder ─────────────────────────────────────────────────────────────
def build_assessment_prompt(rubric, contribution):
    """
    Combine rubric envelope data with student contribution
    into a structured user message for the assessment API call.
    """
    dims_formatted = '\n'.join(f'  - {d}' for d in rubric.get('dimensions', []))

    prompt = f"""RUBRIC ENVELOPE
===============
Contribution ID: {rubric['id']}
Type: {rubric['type']}

Directive given to student:
{rubric['directive']}

Instructional context (what the student was told before this task):
{rubric['narration']}

Standard prompt the student interacted with (S{rubric.get('context_prompt_id', '')}):
{rubric['context_prompt_text']}

Assessment dimensions:
{dims_formatted}

STUDENT SUBMISSION
==================
Context prompt the student ran:
{contribution['context_prompt_text']}

AI response the student received:
{contribution['ai_response']}

Student's contribution:
{contribution['student_text']}

ASSESSMENT INSTRUCTIONS
=======================
Assess the student's contribution using the dimensions above.
Respond using exactly this tagged format — do not deviate:

[assessment id: {rubric['id']}]
band: <Developing | Satisfactory | Strong>
{chr(10).join(f'[dimension: {d}]' + chr(10) + '<your feedback here>' + chr(10) + f'[/dimension]' for d in rubric.get('dimensions', []))}
[summary]
<2-3 sentence summary with one concrete suggestion>
[/summary]
[/assessment]"""

    return prompt


def call_api(user_prompt, system_prompt=ASSESSMENT_SYSTEM_PROMPT):
    """Make the Azure OpenAI API call. Returns response text or None."""
    if not AZURE_ENDPOINT or not AZURE_KEY:
        print("ERROR: AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY must be set.")
        print("Set them as environment variables or edit the CONFIG block in api_builder.py")
        return None

    url = f"{AZURE_ENDPOINT.rstrip('/')}/openai/deployments/{AZURE_DEPLOYMENT}/chat/completions?api-version={API_VERSION}"

    headers = {
        "Content-Type": "application/json",
        "api-key": AZURE_KEY
    }

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 1500,
        "temperature": 0.3   # lower temperature for consistent assessment
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        return data['choices'][0]['message']['content']
    except requests.exceptions.RequestException as e:
        print(f"API call failed: {e}")
        return None
    except (KeyError, IndexError) as e:
        print(f"Unexpected API response format: {e}")
        return None


# ── Assessment output formatter ──────────────────────────────────────────────────
def wrap_assessment_output(raw_response, student_id, contribution_id, lecture_stem):
    """
    Wrap the raw API response in a standardized file with metadata.
    Handles cases where the model response already contains tags
    or returns freeform text.
    """
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')

    lines = []
    lines.append('[assessment_record]')
    lines.append(f'student: {student_id}')
    lines.append(f'contribution_id: {contribution_id}')
    lines.append(f'lecture: {lecture_stem}')
    lines.append(f'timestamp: {timestamp}')
    lines.append(f'model: {AZURE_DEPLOYMENT}')
    lines.append('')
    lines.append(raw_response.strip())
    lines.append('')
    lines.append('[/assessment_record]')

    return '\n'.join(lines)


def extract_student_id(contributions_path):
    """
    Attempt to extract student ID from filename.
    Expects format: <student_id>_L<N>_contributions.txt
    Falls back to full stem if pattern not found.
    """
    stem = Path(contributions_path).stem
    # Try to extract leading ID before first underscore
    parts = stem.split('_')
    if len(parts) >= 1:
        return parts[0]
    return stem


# ── Main processing ──────────────────────────────────────────────────────────────
def process_one(rubric_envelope_path, contributions_path, output_dir):
    """Process one student's contributions file against a rubric envelope."""
    envelope_text = Path(rubric_envelope_path).read_text(encoding='utf-8')
    contributions_text = Path(contributions_path).read_text(encoding='utf-8')

    rubrics = parse_rubric_envelope(envelope_text)
    contributions = parse_contributions(contributions_text)

    if not rubrics:
        print(f"No rubric blocks found in {rubric_envelope_path}")
        return

    if not contributions:
        print(f"No contribution blocks found in {contributions_path}")
        return

    student_id = extract_student_id(contributions_path)
    lecture_stem = Path(rubric_envelope_path).stem.replace('_rubric_envelope', '')
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)

    for contribution in contributions:
        cid = contribution['id']

        if cid not in rubrics:
            print(f"  Warning: no rubric found for contribution {cid} — skipping")
            continue

        rubric = rubrics[cid]
        print(f"  Assessing {student_id} / {cid}...")

        user_prompt = build_assessment_prompt(rubric, contribution)

        # Dry run mode — print prompt instead of calling API
        if '--dry-run' in sys.argv:
            print(f"\n--- DRY RUN: API prompt for {student_id}/{cid} ---")
            print(user_prompt[:2000])
            print("--- END DRY RUN ---\n")
            continue

        raw_response = call_api(user_prompt)
        if raw_response is None:
            print(f"  API call failed for {student_id}/{cid}")
            continue

        output_text = wrap_assessment_output(raw_response, student_id, cid, lecture_stem)
        out_filename = f"{student_id}_{cid.replace('.', '_')}_assessment.txt"
        out_path = output_dir / out_filename
        out_path.write_text(output_text, encoding='utf-8')
        print(f"  Written: {out_path}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]

    if len(args) < 2:
        print("Usage:")
        print("  python api_builder.py <rubric_envelope.txt> <contributions.txt> [output_dir]")
        print("  python api_builder.py <rubric_envelope.txt> --batch <contributions_dir> [output_dir]")
        print("\nOptions:")
        print("  --dry-run    Print API prompt instead of calling API")
        sys.exit(1)

    rubric_path = args[0]

    if '--batch' in sys.argv:
        batch_idx = sys.argv.index('--batch')
        contrib_dir = Path(sys.argv[batch_idx + 1])
        output_dir = Path(args[2]) if len(args) > 2 else contrib_dir / 'assessments'
        contrib_files = list(contrib_dir.glob('*_contributions.txt'))
        print(f"Batch mode: {len(contrib_files)} contribution files found")
        for cf in contrib_files:
            print(f"\nProcessing: {cf.name}")
            process_one(rubric_path, cf, output_dir)
    else:
        contrib_path = args[1]
        output_dir = args[2] if len(args) > 2 else str(Path(contrib_path).parent / 'assessments')
        process_one(rubric_path, contrib_path, output_dir)


if __name__ == '__main__':
    main()
