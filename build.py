import os
import sys
from pathlib import Path

def compile_godprompt():
    root = Path(__file__).parent
    godprompt_path = root / "GodPrompt.md"
    skill_path = root / "SKILL.md"
    protocols_path = root / "references" / "01-PROTOCOLS.md"
    gates_path = root / "references" / "02-GATES.md"
    antipatterns_path = root / "references" / "03-ANTI-PATTERNS.md"
    
    header = (
        "# ============================================================\n"
        "# GODPROMPT — Combined Single-File Version\n"
        "# Paste this entire file into CLAUDE.md or Claude Project Instructions\n"
        "# ============================================================\n\n"
    )
    
    with open(skill_path, 'r', encoding='utf-8') as f:
        skill = f.read()
    with open(protocols_path, 'r', encoding='utf-8') as f:
        protocols = f.read()
    with open(antipatterns_path, 'r', encoding='utf-8') as f:
        antipatterns = f.read()
    with open(gates_path, 'r', encoding='utf-8') as f:
        gates = f.read()
        
    # Apply replacements to adapt file-path references to section-based references
    skill_compiled = skill
    skill_compiled = skill_compiled.replace(
        "Read `references/01-PROTOCOLS.md` for",
        "See the Protocols Reference section below for"
    )
    skill_compiled = skill_compiled.replace(
        "Read `references/01-PROTOCOLS.md → DEBUG`.",
        "See → Protocols Reference → DEBUG below."
    )
    skill_compiled = skill_compiled.replace(
        "`references/01-PROTOCOLS.md`",
        "See → Protocols Reference"
    )
    skill_compiled = skill_compiled.replace(
        "`references/03-ANTI-PATTERNS.md`",
        "See → Anti-Patterns Reference"
    )
    skill_compiled = skill_compiled.replace(
        "`references/02-GATES.md`",
        "See → Quality Gates Reference"
    )
    
    # Assemble the sections with Markdown horizontal rules (separators)
    sections = [
        skill_compiled.strip(),
        protocols.strip(),
        antipatterns.strip(),
        gates.strip()
    ]
    
    compiled = header + "\n\n---\n\n".join(sections) + "\n"
    return compiled

def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--check':
        root = Path(__file__).parent
        godprompt_path = root / "GodPrompt.md"
        with open(godprompt_path, 'r', encoding='utf-8') as f:
            existing = f.read()
        compiled = compile_godprompt()
        
        # Clean trailing whitespace per line for comparison
        compiled_clean = "\n".join(line.rstrip() for line in compiled.splitlines())
        existing_clean = "\n".join(line.rstrip() for line in existing.splitlines())
        
        if compiled_clean != existing_clean:
            print("Error: GodPrompt.md is out of sync with source files.")
            sys.exit(1)
        else:
            print("Success: GodPrompt.md is perfectly in sync.")
            sys.exit(0)
    else:
        root = Path(__file__).parent
        godprompt_path = root / "GodPrompt.md"
        compiled = compile_godprompt()
        with open(godprompt_path, 'w', encoding='utf-8') as f:
            f.write(compiled)
        print("Successfully compiled GodPrompt.md from source files!")

if __name__ == '__main__':
    main()
